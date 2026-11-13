# skillcast.py
#
# 디스패처(길2)로 스킬을 시전하는 모듈. 마우스를 쓰지 않는다.
# sweep_mem.py에서 어스바인드를 혈원에게 거는 데 쓴다.
#
# 원리 (REA 분석, ~/workspace/game/earthbind-skill-code.md):
#   스킬 사용 진입점 FUN_0045e270(스킬코드, 0)을 게임 프로세스 안에서 직접 호출한다.
#   - ECX = self 구조체 포인터 (DAT_005ab548 = 0x5AB548의 값). __thiscall 유사 방식.
#   - FUN_0045e270이 현재 스킬 필드(self+0x454), 쿨다운(DAT_005fd870)을 세팅하고
#     어스바인드 핸들러 FUN_0045c270()으로 넘긴다.
#   - FUN_0045c270()은 대상 id를 DAT_004991e0(현재 선택 타겟)에서 읽어
#     디스패처 FUN_0045a380("cccd", 20, 19, 4, target_id)로 패킷을 보낸다.
#     (어스바인드=156, 156>>3=19, 156&7=4, 총 9바이트. 좌표 없이 대상 id만 보냄.)
#
# 구현:
#   1. 대상 id를 DAT_004991e0(0x4991E0)에 쓴다 (WriteProcessMemory).
#      - 클라이언트 측 선택 상태 변수라 서버 판정 값(HP/MP)이 아니고,
#        게임에서 대상을 클릭해 선택하는 것과 같은 효과다.
#   2. 스텁(머신 코드)을 게임 프로세스에 주입하고 원격 스레드로 실행한다.
#      스텁은 EBP 프레임으로 ESP를 복원해서, 호출 규약(__thiscall/cdecl) 어느 쪽이어도
#      스택이 안 깨진다. 스레드가 끝나면 주입한 메모리를 해제한다.
#
# 주의:
#   - 인젝션(코드 주입)이라 감지 리스크가 있다. 읽기 전용 선을 넘는 방식이다.
#     2026-10-27 사용자가 자동 프로그램 사용으로 계정 밴을 당한 적이 있다.
#   - 메인 스레드 컨텍스트 가설이 여전히 열려 있다. FUN_0045e270은 전역 상태와 UI 함수를
#     건드려서, 원격 스레드(CreateRemoteThread)에서 호출이 실패하거나 게임이 불안정해질 수 있다.
#     그 경우 메인 스레드에서 실행하는 방법(메시지 루프 후킹 등)으로 바꿔야 한다.
#   - 스킬 코드는 REA로 확인: 어스바인드=156 (0x9C), 턴언데드=17.
#     (L1J ID−1 규칙. 턴언데드 17은 CE 실측 패킷과 일치로 검증됨.)
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

SKILL_EARTH_BIND = 156      # 어스바인드 (0x9C)
SKILL_TURN_UNDEAD = 17      # 턴언데드 (참고용)

#=====================================================================
# Windows API
#=====================================================================
PROCESS_VM_OPERATION        = 0x0008
PROCESS_VM_READ             = 0x0010
PROCESS_VM_WRITE            = 0x0020
PROCESS_CREATE_THREAD       = 0x0002
PROCESS_QUERY_INFORMATION   = 0x0400

MEM_COMMIT                  = 0x1000
MEM_RESERVE                 = 0x2000
MEM_RELEASE                 = 0x8000
PAGE_EXECUTE_READWRITE      = 0x40
INFINITE                    = 0xFFFFFFFF
WAIT_OBJECT_0               = 0x00000000
WAIT_TIMEOUT                = 0x00000102

_k32 = ctypes.windll.kernel32
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                                wintypes.DWORD, wintypes.DWORD]
_k32.VirtualAllocEx.restype = wintypes.LPVOID
_k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID,
                                    ctypes.c_size_t,
                                    ctypes.POINTER(ctypes.c_size_t)]
_k32.WriteProcessMemory.restype = wintypes.BOOL
_k32.CreateRemoteThread.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                                    wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD)]
_k32.CreateRemoteThread.restype = wintypes.HANDLE
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.VirtualFreeEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t,
                               wintypes.DWORD]
_k32.VirtualFreeEx.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.restype = wintypes.BOOL


def _build_stub(skill_code):
    """FUN_0045e270(skill_code, 0)을 부르는 스텁 머신 코드 (27바이트, x86).
    ECX=self 포인터(DAT_005ab548 값). EBP 프레임으로 ESP를 복원해서
    호출 규약(__thiscall/cdecl) 어느 쪽이어도 스택이 안 깨진다.
    스킬 코드는 push imm32 자리에 패치한다 (오프셋 12~15)."""
    stub = bytearray([
        0x55,                          # push ebp
        0x89, 0xE5,                    # mov ebp, esp
        0x8B, 0x0D, 0x48, 0xB5, 0x5A, 0x00,  # mov ecx, [0x5AB548]
        0x6A, 0x00,                    # push 0 (param_2)
        0x68, 0x9C, 0x00, 0x00, 0x00,  # push skill_code (imm32, 아래에서 패치)
        0xB8, 0x70, 0xE2, 0x45, 0x00,  # mov eax, 0x45E270
        0xFF, 0xD0,                    # call eax
        0x89, 0xEC,                    # mov esp, ebp
        0x5D,                          # pop ebp
        0xC3,                          # ret
    ])
    # push skill_code imm32 패치 (오프셋 12~15)
    stub[12:16] = struct.pack('<I', skill_code & 0xFFFFFFFF)
    return bytes(stub)


class SkillCaster(object):
    """디스패처로 스킬을 시전한다. 마우스를 쓰지 않는다.
    사용법:
        caster = SkillCaster(pid)
        caster.cast(SKILL_EARTH_BIND, target_id)
        caster.close()
    cast()는 대상 선택(DAT_004991e0 쓰기) + 스텁 주입·실행·해제를 한 번에 한다.
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

    def cast(self, skill_code, target_id, timeout_ms=2000):
        """스킬 시전. skill_code=스킬 코드(어스바인드 156), target_id=대상 id.
        돌려주는 것: True(스레드 정상 종료, 패킷 전송 시도됨) / False(실패·타임아웃).
        True가 패킷이 실제로 나갔다는 보장은 아니다 — 게임 내 스킬 발동 여부는 별도로 확인해야 한다."""
        if self.h is None:
            self.err = '프로세스 핸들 없음: ' + str(self.err)
            return False
        # 1. 대상 선택 (DAT_004991e0에 대상 id 쓰기)
        if not self.set_target(target_id):
            self.err = '대상 선택 쓰기 실패 (DAT_004991e0, 에러 %d)' % _k32.GetLastError()
            return False
        # 2. 스텁 주입
        stub = _build_stub(skill_code)
        mem = _k32.VirtualAllocEx(self.h, None, len(stub),
                                  MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
        if not mem:
            self.err = 'VirtualAllocEx 실패 (에러 %d)' % _k32.GetLastError()
            return False
        try:
            written = ctypes.c_size_t(0)
            ok = _k32.WriteProcessMemory(self.h, mem, stub, len(stub),
                                         ctypes.byref(written))
            if not ok or written.value != len(stub):
                self.err = '스텁 쓰기 실패 (에러 %d)' % _k32.GetLastError()
                return False
            # 3. 원격 스레드로 스텁 실행
            tid = wintypes.DWORD(0)
            h_thread = _k32.CreateRemoteThread(self.h, None, 0, mem, None, 0,
                                               ctypes.byref(tid))
            if not h_thread:
                self.err = 'CreateRemoteThread 실패 (에러 %d)' % _k32.GetLastError()
                return False
            try:
                rc = _k32.WaitForSingleObject(h_thread, timeout_ms)
                if rc == WAIT_TIMEOUT:
                    self.err = '스킬 호출 타임아웃 (%dms)' % timeout_ms
                    return False
                if rc != WAIT_OBJECT_0:
                    self.err = '스레드 대기 실패 (결과 %d, 에러 %d)' % (rc, _k32.GetLastError())
                    return False
                self.err = None
                return True
            finally:
                _k32.CloseHandle(h_thread)
        finally:
            _k32.VirtualFreeEx(self.h, mem, 0, MEM_RELEASE)

    def cast_earth_bind(self, target_id, timeout_ms=2000):
        """어스바인드(156) 시전. target_id=대상(혈원) id."""
        return self.cast(SKILL_EARTH_BIND, target_id, timeout_ms)
