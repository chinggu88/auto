#memcast.py - 대상 id 를 메모리에 써넣고 단축키를 눌러 마법을 시전한다.
#memread.py 는 읽기 전용으로 남기고 쓰기는 이 파일에만 둔다.
#쓰는 것은 spell_target 4바이트뿐이고 코드 주입은 없다.

import ctypes
import struct
import time

import pyautogui as gu

import memread as mr

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE     = 0x0020

CAST_WAIT   = 0.3    #초. 키를 누른 뒤 클라이언트가 처리할 때까지 기다리는 최대 시간
CAST_STEP   = 0.01
CAST_SETTLE = 0.02   #처리 감지 후 대상 값을 되돌리기 전에 두는 여유

#argtypes 를 안 정하면 64비트에서 핸들/주소가 조용히 잘린다 (memread.py 와 같은 이유)
if mr.IS_WIN:
    mr.k32.WriteProcessMemory.argtypes = [mr.wt.HANDLE, mr.wt.LPVOID, mr.wt.LPCVOID,
                                          ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    mr.k32.WriteProcessMemory.restype  = mr.wt.BOOL


#쓰기 권한으로 프로세스를 연다. 실패하면 None
def openwrite(pid):
    if not mr.IS_WIN:
        return None
    h = mr.k32.OpenProcess(PROCESS_VM_WRITE | PROCESS_VM_OPERATION, False, int(pid))
    if h:
        return int(h)
    return None


#실제 쓰기. data 는 bytes. 부분 쓰기도 실패로 본다
def writemem(h, addr, data):
    if not mr.IS_WIN or not h or addr <= 0:
        return False
    buf  = ctypes.create_string_buffer(data, len(data))
    put  = ctypes.c_size_t(0)
    okay = mr.k32.WriteProcessMemory(mr.wt.HANDLE(h), ctypes.c_void_p(int(addr)),
                                     buf, ctypes.c_size_t(len(data)), ctypes.byref(put))
    if not okay or put.value != len(data):
        return False
    return True


class Caster:
    def __init__(self, mem):
        self.mem = mem      #붙어 있는 mr.Mem
        self.h   = None     #우리가 따로 연 쓰기 핸들
        self.pid = None

    def close(self):
        if self.h:
            mr.closeproc(self.h)
        self.h   = None
        self.pid = None

    def _open(self):
        if self.h != None and self.pid == self.mem.pid:
            return True
        self.close()
        h = openwrite(self.mem.pid)
        if h == None:
            return False
        self.h   = h
        self.pid = self.mem.pid
        return True

    #Mem.lock 은 재진입이 안 되고 value() 가 직접 잡으므로, 잡은 채로 value() 를 부르면 안 된다
    def _addr(self, name):
        spec = (self.mem.cfg.get('chains') or {}).get(name)
        if spec == None:
            return None
        with self.mem.lock:
            return self.mem.resolve(spec)

    #avoid = 누르면 안 되는 키 이름들 (호출한 쪽이 전역 단축키로 쓰는 키)
    def cast(self, target_id, ent_ptr, avoid=()):
        key = None
        if self.mem == None or self.mem.h == None:
            return {'state': 'error', 'key': key, 'msg': '게임에 안 붙음'}

        sel = self.mem.value('hotkey_sel')
        if sel == None or not (0 <= sel <= 7):
            return {'state': 'error', 'key': key, 'msg': '선택된 단축키를 못 읽음'}
        key = 'f%d' % (5 + sel)
        if key in avoid:
            return {'state': 'error', 'key': key, 'msg': '다른 기능이 쓰는 키라 누르지 않음'}

        #키 입력이 다른 창으로 가는 것을 막는다
        if mr.frontpid() != self.mem.pid:
            return {'state': 'nofocus', 'key': key, 'msg': '게임 창이 맨 앞이 아님'}

        #엔티티 +0x1A 가 0 이 아니면 클라이언트가 고정 대상을 무시하고 대상 선택 모드로 들어간다
        flag = None
        if ent_ptr:
            flag = mr.readmem(self.mem.h, ent_ptr + 0x1A, 1)
        if flag == None or flag[0] != 0:
            return {'state': 'skip', 'key': key, 'msg': '대상 상태 때문에 건너뜀'}

        addr = self._addr('spell_target')
        old  = self.mem.value('spell_target')
        t0   = self.mem.value('hotkey_time')
        r0   = self.mem.value('cast_ready')
        if addr == None or old == None or t0 == None or r0 == None:
            return {'state': 'error', 'key': key, 'msg': 'mem.json 시전 체인을 못 읽음'}

        if not self._open():
            return {'state': 'error', 'key': key, 'msg': '쓰기 권한으로 프로세스를 못 엶'}

        if not writemem(self.h, addr, struct.pack('<I', int(target_id) & 0xFFFFFFFF)):
            return {'state': 'error', 'key': key, 'msg': '대상 id 쓰기 실패'}

        t1 = t0
        try:
            gu.press(key)
            end = time.time() + CAST_WAIT
            while time.time() < end:
                v = self.mem.value('hotkey_time')
                if v != None and v != t0:
                    t1 = v
                    time.sleep(CAST_SETTLE)
                    break
                time.sleep(CAST_STEP)
        finally:
            #사용자가 직접 쓰는 마법이 이 대상으로 끌려가지 않게 원래 값으로 되돌린다
            writemem(self.h, addr, struct.pack('<I', old))

        if t1 == t0:
            return {'state': 'nokey', 'key': key, 'msg': '키 입력이 게임에 안 들어감'}
        r1 = self.mem.value('cast_ready')
        if r1 != None and r1 != r0:
            return {'state': 'sent', 'key': key, 'msg': '시전됨'}
        return {'state': 'nocast', 'key': key, 'msg': '시전 안 됨 (쿨타임/사거리)'}
