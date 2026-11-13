# skillcast.py
#
# 디스패처(길2)로 스킬을 시전하는 모듈. 마우스를 쓰지 않는다.
# sweep_mem.py에서 아이언 스킨을 혈원에게 거는 데 쓴다.
#
# 원리 (REA 분석, ~/workspace/game/iron-skin-skill-code.md):
#   스킬 사용 진입점 FUN_0045e270(스킬코드, 0)을 게임 프로세스 안에서 직접 호출한다.
#   - ECX = self 구조체 포인터 (DAT_005ab548 = 0x5AB548의 값). __thiscall 유사 방식.
#   - FUN_0045e270이 현재 스킬 필드(self+0x454), 쿨다운(DAT_005fd870)을 세팅하고
#     아이언 스킨 핸들러 FUN_0045c270()으로 넘긴다.
#   - FUN_0045c270()은 대상 id를 DAT_004991e0(현재 선택 타겟)에서 읽어
#     디스패처 FUN_0045a380("cccd", 20, 20, 7, target_id)로 패킷을 보낸다.
#     (아이언 스킨=167, 167>>3=20, 167&7=7, 총 9바이트. 좌표 없이 대상 id만 보냄.)
#   - 정정 (2026-11-13): 사용자가 쓰려는 스킬은 어스바인드가 아니라 아이언 스킨이다.
#     어스바인드 코드 156은 잘못된 스킬이었음. EARTH_SKIN(150)과 IRON_SKIN(167)은 별개 스킬.
#
# 실행 방식 (v2 — 원격 스레드에서 APC로 변경):
#   v1은 CreateRemoteThread로 스텁을 실행했는데 게임이 팅겼다 (2026-11-13).
#   FUN_0045e270은 전역 상태와 UI 함수를 건드려서 메인 스레드가 아닌 곳에서 부르면
#   불안정할 수 있다. 그래서 v2는 게임 메인 스레드에 APC(QueueUserAPC)로 스텁을 큐잉한다.
#   메인 스레드가 alertable wait(SleepEx/메시지 루프 등)에 들어가면 APC가 실행된다.
#   메인 스레드는 게임 창("Lineage Windows Client")의 소유 스레드로 찾는다.
#
# 구현:
#   1. self 포인터(DAT_005ab548)를 읽어 0이 아닌지 확인한다 (0이면 호출 안 함 — 크래시 방지).
#   2. 대상 id를 DAT_004991e0(0x4991E0)에 쓴다 (WriteProcessMemory).
#      - 클라이언트 측 선택 상태 변수라 서버 판정 값(HP/MP)이 아니고,
#        게임에서 대상을 클릭해 선택하는 것과 같은 효과다.
#   3. 스텁(머신 코드) + 완료 플래그(4바이트)를 게임 프로세스에 할당·기록한다.
#      스텁은 EBP 프레임으로 ESP를 복원해서, 호출 규약(__thiscall/cdecl) 어느 쪽이어도
#      스택이 안 깨진다. ECX(self 포인터)가 0이면 호출을 건너뛰고 완료만 찍는다.
#   4. 메인 스레드에 APC로 스텁을 큐잉하고, 완료 플래그가 1이 될 때까지 폴링한다.
#   5. 완료되면(또는 타임아웃) 할당한 메모리를 해제한다.
#
# 주의:
#   - 인젝션(코드 주입)이라 감지 리스크가 있다. 읽기 전용 선을 넘는 방식이다.
#     2026-10-27 사용자가 자동 프로그램 사용으로 계정 밴을 당한 적이 있다.
#   - APC가 실행되려면 메인 스레드가 alertable wait에 들어가야 한다.
#     타임아웃(기본 3초) 안에 완료 플래그가 안 서면 실패로 보고 다음으로 넘어간다.
#   - 스킬 코드는 REA로 확인: 아이언 스킨=167 (0xA7), 턴언데드=17.
#     (L1J ID−1 규칙. 턴언데드 17은 CE 실측 패킷과 일치로 검증됨.)
#     어스바인드=156은 잘못된 스킬이었음 (2026-11-13 정정, iron-skin-skill-code.md 참조).
#   - 아이언 스킨 쿨다운 테이블 값(0x4915A0 + 167*2)은 0으로 확인됨 (REA, 파일에서 직접 읽음).
#     쿨다운 게이트가 없어서 CAST_COOLDOWN 0.5초 간격으로 쏘는 데 지장 없다.
#
# 같은 폴더에 memread.py가 있어야 한다 (PID를 얻기 위해).
# 실행은 sweep_mem.py에서 한다. 이 파일 단독으로는 동작하지 않는다.

import ctypes
import struct
import time
from ctypes import wintypes

#=====================================================================
# 주소·상수 (REA 분석으로 확인)
#=====================================================================
FUNC_SKILL_USE = 0x45E270   # FUN_0045e270 : 스킬 사용 진입점
ADDR_SELF_PTR  = 0x5AB548   # DAT_005ab548 : self 구조체 포인터
ADDR_TARGET_SEL = 0x4991E0  # DAT_004991e0 : 현재 선택 타겟 id (4바이트)

SKILL_IRON_SKIN = 167        # 아이언 스킨 (0xA7)
SKILL_TURN_UNDEAD = 17      # 턴언데드 (참고용)

GAME_WINDOW_TITLE = 'Lineage Windows Client'  # 메인 스레드 찾기용 창 제목

#=====================================================================
# Windows API
#=====================================================================
PROCESS_VM_OPERATION        = 0x0008
PROCESS_VM_READ             = 0x0010
PROCESS_VM_WRITE            = 0x0020
PROCESS_CREATE_THREAD       = 0x0002
PROCESS_QUERY_INFORMATION   = 0x0400

THREAD_SET_CONTEXT          = 0x0010
THREAD_QUERY_INFORMATION    = 0x0040

MEM_COMMIT                  = 0x1000
MEM_RESERVE                 = 0x2000
MEM_RELEASE                 = 0x8000
PAGE_EXECUTE_READWRITE      = 0x40

_k32 = ctypes.windll.kernel32
_u32 = ctypes.windll.user32
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                                wintypes.DWORD, wintypes.DWORD]
_k32.VirtualAllocEx.restype = wintypes.LPVOID
_k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID,
                                    ctypes.c_size_t,
                                    ctypes.POINTER(ctypes.c_size_t)]
_k32.WriteProcessMemory.restype = wintypes.BOOL
_k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
                                   ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_size_t)]
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
_u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                          ctypes.POINTER(wintypes.DWORD)]
_u32.GetWindowThreadProcessId.restype = wintypes.DWORD


def _build_stub(skill_code, flag_addr):
    """FUN_0045e270(skill_code, 0)을 부르는 APC 스텁 머신 코드 (42바이트, x86).
    ECX=self 포인터(DAT_005ab548 값). ECX가 0이면 호출을 건너뛴다.
    끝나면 flag_addr에 1을 써서 완료를 알린다 (폴링용).
    EBP 프레임으로 ESP를 복원해서 호출 규약(__thiscall/cdecl) 어느 쪽이어도 스택이 안 깨진다.
    skill_code는 push imm32 자리(오프셋 16~19), flag_addr은 mov eax imm32 자리(오프셋 28~31)에 패치한다."""
    stub = bytearray([
        0x55,                          # push ebp
        0x89, 0xE5,                    # mov ebp, esp
        0x8B, 0x0D, 0x48, 0xB5, 0x5A, 0x00,  # mov ecx, [0x5AB548]
        0x85, 0xC9,                    # test ecx, ecx
        0x74, 0x0E,                    # jz done (다음 명령 +14)
        0x6A, 0x00,                    # push 0 (param_2)
        0x68, 0x9C, 0x00, 0x00, 0x00,  # push skill_code (imm32, 아래에서 패치)
        0xB8, 0x70, 0xE2, 0x45, 0x00,  # mov eax, 0x45E270
        0xFF, 0xD0,                    # call eax
        # done:
        0xB8, 0x00, 0x00, 0x00, 0x00,  # mov eax, flag_addr (imm32, 아래에서 패치)
        0xC7, 0x00, 0x01, 0x00, 0x00, 0x00,  # mov dword [eax], 1
        0x89, 0xEC,                    # mov esp, ebp
        0x5D,                          # pop ebp
        0xC3,                          # ret
    ])
    # push skill_code imm32 패치 (오프셋 16~19)
    stub[16:20] = struct.pack('<I', skill_code & 0xFFFFFFFF)
    # mov eax, flag_addr imm32 패치 (오프셋 28~31)
    stub[28:32] = struct.pack('<I', flag_addr & 0xFFFFFFFF)
    return bytes(stub)


def _find_main_thread_id(pid):
    """게임 창("Lineage Windows Client")의 소유 스레드 id를 돌려준다. 못 찾으면 None."""
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


class SkillCaster(object):
    """디스패처로 스킬을 시전한다. 마우스를 쓰지 않는다. 메인 스레드 APC 방식.
    사용법:
        caster = SkillCaster(pid)
        caster.cast(SKILL_IRON_SKIN, target_id)
        caster.close()
    cast()는 self 포인터 확인 + 대상 선택(DAT_004991e0 쓰기) + 스텁 APC 큐잉·완료 대기를 한 번에 한다.
    """

    def __init__(self, pid):
        self.pid = pid
        self.h = None
        self.err = None
        access = (PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE |
                  PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION)
        h = _k32.OpenProcess(access, False, int(pid))
        if not h:
            self.err = 'OpenProcess 실패 (PID %d, 에러 %d)' % (pid, _k32.GetLastError())
            return
        self.h = h

    def close(self):
        if self.h:
            _k32.CloseHandle(self.h)
            self.h = None

    def _read_u32(self, addr):
        """게임 메모리에서 4바이트(u32)를 읽는다. 못 읽으면 None."""
        if self.h is None:
            return None
        buf = ctypes.create_string_buffer(4)
        read = ctypes.c_size_t(0)
        ok = _k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, 4,
                                    ctypes.byref(read))
        if not ok or read.value != 4:
            return None
        return struct.unpack('<I', buf.raw)[0]

    def _write_u32(self, addr, value):
        """게임 메모리에 4바이트(u32)를 쓴다. 성공하면 True."""
        if self.h is None:
            return False
        buf = struct.pack('<I', value & 0xFFFFFFFF)
        written = ctypes.c_size_t(0)
        ok = _k32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), buf,
                                     len(buf), ctypes.byref(written))
        return bool(ok) and written.value == len(buf)

    def set_target(self, target_id):
        """대상 id를 DAT_004991e0(현재 선택 타겟)에 쓴다.
        FUN_0045c270이 이 값을 읽어 디스패처에 target_id로 넘긴다."""
        return self._write_u32(ADDR_TARGET_SEL, target_id)

    def cast(self, skill_code, target_id, timeout_ms=3000):
        """스킬 시전. skill_code=스킬 코드(아이언 스킨 167), target_id=대상 id.
        돌려주는 것: True(스텁이 메인 스레드에서 실행 완료됨) / False(실패·타임아웃).
        True가 패킷이 실제로 나갔다는 보장은 아니다 — 게임 내 스킬 발동 여부는 별도로 확인해야 한다."""
        if self.h is None:
            self.err = '프로세스 핸들 없음: ' + str(self.err)
            return False
        # 0. self 포인터 확인 (0이면 FUN_0045e270이 *(0+0x454)에 써서 크래시 나니까 호출 안 함)
        self_ptr = self._read_u32(ADDR_SELF_PTR)
        if self_ptr is None:
            self.err = 'self 포인터 읽기 실패 (DAT_005ab548)'
            return False
        if self_ptr == 0:
            self.err = 'self 포인터가 0 (캐릭터 로딩 안 됨?)'
            return False
        # 1. 대상 선택 (DAT_004991e0에 대상 id 쓰기)
        if not self.set_target(target_id):
            self.err = '대상 선택 쓰기 실패 (DAT_004991e0, 에러 %d)' % _k32.GetLastError()
            return False
        # 2. 메인 스레드 찾기
        tid = _find_main_thread_id(self.pid)
        if tid is None:
            self.err = '게임 메인 스레드를 못 찾음 (창 제목: %s)' % GAME_WINDOW_TITLE
            return False
        h_thread = _k32.OpenThread(THREAD_SET_CONTEXT | THREAD_QUERY_INFORMATION,
                                   False, tid)
        if not h_thread:
            self.err = 'OpenThread 실패 (TID %d, 에러 %d)' % (tid, _k32.GetLastError())
            return False
        try:
            # 3. 스텁 + 완료 플래그 할당·기록
            #    [stub (42바이트)][flag (4바이트)] 를 한 블록으로 할당한다.
            stub_len = 42
            total = stub_len + 4
            mem = _k32.VirtualAllocEx(self.h, None, total,
                                      MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
            if not mem:
                self.err = 'VirtualAllocEx 실패 (에러 %d)' % _k32.GetLastError()
                return False
            try:
                flag_addr = mem + stub_len
                stub = _build_stub(skill_code, flag_addr)
                written = ctypes.c_size_t(0)
                ok = _k32.WriteProcessMemory(self.h, mem, stub, len(stub),
                                             ctypes.byref(written))
                if not ok or written.value != len(stub):
                    self.err = '스텁 쓰기 실패 (에러 %d)' % _k32.GetLastError()
                    return False
                # 플래그 0으로 초기화
                if not self._write_u32(flag_addr, 0):
                    self.err = '플래그 초기화 실패 (에러 %d)' % _k32.GetLastError()
                    return False
                # 4. 메인 스레드에 APC 큐잉
                rc = _k32.QueueUserAPC(ctypes.c_void_p(mem), h_thread, None)
                if rc == 0:
                    self.err = 'QueueUserAPC 실패 (에러 %d)' % _k32.GetLastError()
                    return False
                # 5. 완료 플래그 폴링
                deadline = time.time() + timeout_ms / 1000.0
                while time.time() < deadline:
                    v = self._read_u32(flag_addr)
                    if v == 1:
                        self.err = None
                        return True
                    time.sleep(0.02)
                self.err = 'APC 완료 타임아웃 (%dms, 메인 스레드가 alertable wait에 안 들어감?)' % timeout_ms
                return False
            finally:
                _k32.VirtualFreeEx(self.h, mem, 0, MEM_RELEASE)
        finally:
            _k32.CloseHandle(h_thread)

    def cast_iron_skin(self, target_id, timeout_ms=3000):
        """아이언 스킨(167) 시전. target_id=대상(혈원) id."""
        return self.cast(SKILL_IRON_SKIN, target_id, timeout_ms)
