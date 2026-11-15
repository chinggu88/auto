# itemcast.py
#
# 소지품(인벤토리) 아이템을 "바로" 사용하는 모듈. 단축키 칸을 거치지 않는다.
# 마우스/키보드 입력을 쓰지 않고, 게임 함수를 프로세스 안에서 직접 호출한다 (CLAUDE.md "방법 2").
# manapot.py 에서 농축마력의물약을 쓰는 데 쓴다. skillcast.py 의 스킬 버전과 짝이다.
#
# 원리 (REA 분석, Lin.exe Ghidra 12.2 실측):
#   평범하게 쓰는(자기 자신에게 쓰는) 아이템은 단축키 처리기 FUN_0042c110 의
#   default 분기에서 아래 한 줄로 끝난다 :
#       FUN_0045a380("cds", 0x1C, item_id, "")
#   - "cds" (RVA 0x86834) : 패킷 포맷 (c=1바이트, d=4바이트, s=문자열)
#   - 0x1C (28)           : "아이템 사용" 패킷 opcode
#   - item_id             : 인벤토리 엔트리 +0x04 의 아이템 객체 id (u32)
#   - "" (RVA 0x992b4)    : 빈 문자열 (추가 인자 없음)
#   FUN_0045a380 (RVA 0x5A380) 는 cdecl 가변인자다 (RET 로 끝나 호출자가 스택을 정리).
#   내부에서 FUN_0045a1b0 으로 패킷을 만들고 FUN_0045a050(mySend) 으로 보낸다.
#   스킬 진입점 FUN_0045e270 과 달리 self 포인터(DAT_005ab548)를 안 읽으므로,
#   그 값이 0 이라 skillcast.py 를 막았던 문제가 여기엔 없다.
#
# 실행 방식 (skillcast.py 와 같은 메인 스레드 APC 방식):
#   FUN_0045a380 은 전송 버퍼(0x5FABE4)와 XOR 롤링키(0x5FABD0) 같은 전역을 건드린다.
#   다른 스레드에서 부르면 메인 스레드의 전송과 겹쳐 암호화 체인이 어긋날 수 있다.
#   그래서 게임 메인 스레드에 APC(QueueUserAPC)로 스텁을 큐잉한다. 메인 스레드가
#   alertable wait 에 들어가야 APC 가 실행된다. CreateRemoteThread 는 과거에 팅겼다(2026-11-13).
#
# 구현:
#   1. [스텁(45바이트)][완료 플래그(4)]["cds\0"(4)]["\0"(1)] 한 블록을 게임에 할당·기록한다.
#   2. 스텁은 EBP 프레임으로 ESP 를 복원하고, 끝나면 완료 플래그에 1 을 쓴다 (폴링용).
#      item_id / 함수 주소 / 문자열 주소는 호출할 때 실제 값으로 패치한다.
#   3. 메인 스레드에 APC 로 스텁을 큐잉하고 완료 플래그가 1 이 될 때까지 기다린다 (기본 3초).
#   4. 끝나면(또는 타임아웃) 할당한 메모리를 해제한다.
#
# 주의 (CLAUDE.md 규칙 3):
#   코드 주입이라 감지/밴 리스크가 있다 (2026-10-27 밴 전력). 사용자가 방법 2 를 택한 결정에 따른다.
#   APC 가 실행되려면 메인 스레드가 alertable wait 에 들어가야 한다 (미검증).
#   대상 선택이 필요한 아이템(사용 종류 5/7/8/0xE/0x11/0x1A/0x1B 등)은 이 '바로 사용' 으로는
#   안 된다 — 물약처럼 자기에게 쓰는 평범한 아이템만 된다.
#
# 같은 폴더에 memread.py 가 있어야 한다 (모듈 베이스를 얻을 때 쓴다).

import ctypes
import struct
import time
from ctypes import wintypes

#=====================================================================
# 주소 (RVA - 모듈 베이스로부터의 상대값. use() 에서 베이스를 더한다)
#=====================================================================
RVA_SEND_FMT_FUNC = 0x5A380     # FUN_0045a380 : 포맷 패킷 전송 (cdecl 가변인자)
OP_USE_ITEM       = 0x1C        # "아이템 사용" 패킷 opcode

GAME_WINDOW_TITLE = 'Lineage Windows Client'   # 메인 스레드 찾기용 창 제목

#=====================================================================
# Windows API
#=====================================================================
PROCESS_VM_OPERATION      = 0x0008
PROCESS_VM_READ           = 0x0010
PROCESS_VM_WRITE          = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400

THREAD_SET_CONTEXT        = 0x0010
THREAD_QUERY_INFORMATION  = 0x0040

MEM_COMMIT             = 0x1000
MEM_RESERVE            = 0x2000
MEM_RELEASE            = 0x8000
PAGE_EXECUTE_READWRITE = 0x40

_k32 = ctypes.windll.kernel32 if hasattr(ctypes, 'windll') else None
_u32 = ctypes.windll.user32 if hasattr(ctypes, 'windll') else None

if _k32 is not None:
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                                    wintypes.DWORD, wintypes.DWORD]
    _k32.VirtualAllocEx.restype = wintypes.LPVOID
    _k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    _k32.WriteProcessMemory.restype = wintypes.BOOL
    _k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    _k32.ReadProcessMemory.restype = wintypes.BOOL
    _k32.VirtualFreeEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                                   wintypes.DWORD]
    _k32.VirtualFreeEx.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenThread.restype = wintypes.HANDLE
    _k32.QueueUserAPC.argtypes = [wintypes.LPVOID, wintypes.HANDLE, wintypes.LPVOID]
    _k32.QueueUserAPC.restype = wintypes.DWORD
    _u32.FindWindowA.argtypes = [wintypes.LPCSTR, wintypes.LPCSTR]
    _u32.FindWindowA.restype = wintypes.HWND
    _u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _u32.GetWindowThreadProcessId.restype = wintypes.DWORD


def _build_stub(func_addr, item_id, flag_addr, fmt_addr, empty_addr):
    """FUN_0045a380("cds", 0x1C, item_id, "") 를 부르는 APC 스텁 (45바이트, x86).
    cdecl 가변인자라 인자를 오른쪽부터 밀어 넣고 (push ""/item_id/0x1C/"cds") 호출 뒤
    add esp,0x10 으로 치운다. 끝나면 flag_addr 에 1 을 써서 완료를 알린다.
    EBP 프레임으로 ESP 를 복원하므로 APC 호출 규약과 상관없이 스택이 안 깨진다."""
    stub = bytearray([
        0x55,                          # push ebp
        0x89, 0xE5,                    # mov ebp, esp
        0x68, 0, 0, 0, 0,              # push empty_addr   (""), [4:8]
        0x68, 0, 0, 0, 0,              # push item_id,            [9:13]
        0x6A, 0x1C,                    # push 0x1C (opcode)
        0x68, 0, 0, 0, 0,              # push fmt_addr ("cds"),   [16:20]
        0xB8, 0, 0, 0, 0,              # mov eax, func_addr,      [21:25]
        0xFF, 0xD0,                    # call eax
        0x83, 0xC4, 0x10,              # add esp, 0x10  (cdecl 정리)
        0xB8, 0, 0, 0, 0,              # mov eax, flag_addr,      [31:35]
        0xC7, 0x00, 0x01, 0x00, 0x00, 0x00,   # mov dword [eax], 1
        0x89, 0xEC,                    # mov esp, ebp
        0x5D,                          # pop ebp
        0xC3,                          # ret
    ])
    stub[4:8]   = struct.pack('<I', empty_addr & 0xFFFFFFFF)
    stub[9:13]  = struct.pack('<I', item_id & 0xFFFFFFFF)
    stub[16:20] = struct.pack('<I', fmt_addr & 0xFFFFFFFF)
    stub[21:25] = struct.pack('<I', func_addr & 0xFFFFFFFF)
    stub[31:35] = struct.pack('<I', flag_addr & 0xFFFFFFFF)
    return bytes(stub)


def _find_main_thread_id(pid):
    """게임 창의 소유 스레드 id. 못 찾으면 None."""
    if _u32 is None:
        return None
    try:
        hwnd = _u32.FindWindowA(None, GAME_WINDOW_TITLE.encode('utf-8'))
    except Exception:
        return None
    if not hwnd:
        return None
    proc_id = wintypes.DWORD(0)
    tid = _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
    if tid == 0 or proc_id.value != int(pid):
        return None
    return int(tid)


class ItemCaster(object):
    """소지품 아이템을 바로 사용한다 (방법 2, 메인 스레드 APC).
    사용법:
        caster = ItemCaster(pid, base)   # base = Lin.exe 모듈 베이스 (mr.Mem.base)
        caster.use(item_id)              # 인벤토리 엔트리 +0x04 의 아이템 객체 id
        caster.close()
    use() 는 True(스텁이 메인 스레드에서 실행 완료) / False(실패·타임아웃) 를 돌려준다.
    True 가 서버가 실제로 아이템을 먹었다는 보장은 아니다 (쿨타임/사거리/수량은 별도)."""

    def __init__(self, pid, base):
        self.pid  = pid
        self.base = int(base)
        self.h    = None
        self.err  = None
        if _k32 is None:
            self.err = 'Windows 전용 (kernel32 없음)'
            return
        access = (PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE |
                  PROCESS_QUERY_INFORMATION)
        h = _k32.OpenProcess(access, False, int(pid))
        if not h:
            self.err = 'OpenProcess 실패 (PID %d, 에러 %d)' % (pid, ctypes.get_last_error())
            return
        self.h = h

    def close(self):
        if self.h:
            _k32.CloseHandle(self.h)
            self.h = None

    def _write(self, addr, data):
        put = ctypes.c_size_t(0)
        ok = _k32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data),
                                     ctypes.byref(put))
        return bool(ok) and put.value == len(data)

    def _read_u32(self, addr):
        buf = ctypes.create_string_buffer(4)
        got = ctypes.c_size_t(0)
        ok = _k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, 4, ctypes.byref(got))
        if not ok or got.value != 4:
            return None
        return struct.unpack('<I', buf.raw)[0]

    def use(self, item_id, timeout_ms=3000):
        """아이템 객체 id 를 '사용' 한다 (평범한 자기 사용 아이템 전용)."""
        if self.h is None:
            self.err = '프로세스 핸들 없음: ' + str(self.err)
            return False
        if not self.base:
            self.err = '모듈 베이스가 0 (ItemCaster(pid, base) 에 베이스를 줘야 한다)'
            return False
        item_id = int(item_id) & 0xFFFFFFFF

        tid = _find_main_thread_id(self.pid)
        if tid is None:
            self.err = '게임 메인 스레드를 못 찾음 (창 제목: %s)' % GAME_WINDOW_TITLE
            return False
        h_thread = _k32.OpenThread(THREAD_SET_CONTEXT | THREAD_QUERY_INFORMATION, False, tid)
        if not h_thread:
            self.err = 'OpenThread 실패 (TID %d, 에러 %d)' % (tid, ctypes.get_last_error())
            return False
        try:
            #[스텁(45)][플래그(4)]["cds\0"(4)]["\0"(1)] = 54바이트. 넉넉히 64 할당
            stub_len = 45
            total    = 64
            mem = _k32.VirtualAllocEx(self.h, None, total, MEM_COMMIT | MEM_RESERVE,
                                      PAGE_EXECUTE_READWRITE)
            if not mem:
                self.err = 'VirtualAllocEx 실패 (에러 %d)' % ctypes.get_last_error()
                return False
            try:
                flag_addr  = mem + stub_len          # +45
                fmt_addr   = mem + stub_len + 4       # +49  "cds\0"
                empty_addr = mem + stub_len + 8       # +53  "\0"
                func_addr  = self.base + RVA_SEND_FMT_FUNC

                stub = _build_stub(func_addr, item_id, flag_addr, fmt_addr, empty_addr)
                if not self._write(mem, stub):
                    self.err = '스텁 쓰기 실패 (에러 %d)' % ctypes.get_last_error()
                    return False
                if not self._write(flag_addr, struct.pack('<I', 0)):
                    self.err = '플래그 초기화 실패'
                    return False
                if not self._write(fmt_addr, b'cds\x00'):
                    self.err = '포맷 문자열 쓰기 실패'
                    return False
                if not self._write(empty_addr, b'\x00'):
                    self.err = '빈 문자열 쓰기 실패'
                    return False

                rc = _k32.QueueUserAPC(ctypes.c_void_p(mem), h_thread, None)
                if rc == 0:
                    self.err = 'QueueUserAPC 실패 (에러 %d)' % ctypes.get_last_error()
                    return False

                deadline = time.time() + timeout_ms / 1000.0
                while time.time() < deadline:
                    if self._read_u32(flag_addr) == 1:
                        self.err = None
                        return True
                    time.sleep(0.02)
                self.err = 'APC 완료 타임아웃 (%dms, 메인 스레드가 alertable wait 에 안 들어감?)' % timeout_ms
                return False
            finally:
                _k32.VirtualFreeEx(self.h, mem, 0, MEM_RELEASE)
        finally:
            _k32.CloseHandle(h_thread)
