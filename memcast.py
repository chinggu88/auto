#memcast.py - 대상 id 를 메모리에 써넣고 단축키를 눌러 마법을 시전한다.
#누르는 키는 지정한 이름의 마법이 들어 있는 단축키 칸(F5~F12)이고, 메모리에서 찾는다.
#이름으로 못 찾으면 게임에서 클릭해 둔 칸을 대신 누르고, 그렇다고 msg 에 적는다.
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

HOTKEY_N   = 8       #단축키 칸 수 (F5~F12)
HOTKEY_LEN = 0x30    #칸 하나의 이름 바이트수

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


#클라이언트의 이름 비교를 그대로 옮긴 것. a = 풀어 쓴 단축키 이름, b = 배운 마법 이름 (둘 다 bytes)
#앞의 역슬래시 + 1바이트는 버리고, a 가 b 의 앞부분이면 같은 것으로 본다 (대소문자 구분)
def samename(a, b):
    if a[:1] == b'\\':
        a = a[2:]
    if b[:1] == b'\\':
        b = b[2:]
    a = a[:HOTKEY_LEN]
    return b[:len(a)] == a


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

    #주소에서 널 전까지 bytes 로 읽는다. 끝까지 못 읽으면 같은 4KiB 페이지 안의 남은 만큼만 다시 읽는다
    def _cstr(self, addr, maxlen):
        if addr == None or addr <= 0:
            return None
        raw = mr.readmem(self.mem.h, addr, maxlen)
        if raw == None:
            left = 0x1000 - (addr & 0xFFF)
            if left >= maxlen:
                return None
            raw = mr.readmem(self.mem.h, addr, left)
            if raw == None:
                return None
        cut = raw.find(b'\x00')
        if cut >= 0:
            raw = raw[:cut]
        return raw

    #단축키 이름의 $ 표기를 클라이언트처럼 푼다. $숫자 = 문자열 표의 n번째, $글자 = 글자 그대로
    def _expand(self, raw):
        out = b''
        i   = 0
        n   = len(raw)
        while i < n:
            c = raw[i:i + 1]
            if c != b'$':
                out += c
                i   += 1
                continue
            i += 1
            if i >= n:
                break
            if not (0x30 <= raw[i] <= 0x39):
                out += raw[i:i + 1]
                i   += 1
                continue
            j = i
            while j < n and 0x30 <= raw[j] <= 0x39:
                j += 1
            idx = int(raw[i:j])
            i   = j
            if i < n and raw[i:i + 1] == b';':
                i += 1
            rep   = b'???'
            count = self.mem.value('str_count')
            base  = self.mem.value('str_table')
            if count != None and base != None and 0 <= idx < count:
                p = mr.readmem(self.mem.h, base + 4 * idx, 4)
                if p != None:
                    s = self._cstr(struct.unpack('<I', p)[0], 0x100)
                    if s != None:
                        rep = s
            out += rep
        return out

    #이름이 spell 인 마법이 들어 있는 단축키 키를 찾는다. (키 or None, 못 찾은 이유)
    def _findkey(self, spell, avoid):
        spells, win, count = self.mem.spell_table()
        if win == None:
            return None, '스킬 창을 못 읽음'

        ents = []
        for e in spells:
            raw = self._cstr(e['name_ptr'], 64)
            if raw != None:
                ents.append((e, raw, raw.decode(self.mem.enc, 'ignore')))

        def norm(s):
            if s[:1] == '\\':
                s = s[2:]
            return ''.join(s.split())

        want = norm(spell)
        wanted = None
        for e, raw, text in ents:
            if norm(text) == want:
                wanted = e
                break
        if wanted == None and want != '':
            part = [(e, text) for e, raw, text in ents if want in norm(text)]
            if len(part) == 1:
                wanted = part[0][0]
            elif len(part) > 1:
                return None, "'%s' 이(가) 들어간 마법이 여러 개: %s" % (spell, ', '.join([t.strip() for e, t in part]))
        if wanted == None:
            shown = [text.strip() for e, raw, text in ents if text.strip() != '']
            tail  = ''
            if len(shown) > 0:
                tail = ': ' + ', '.join(shown[:8])
                if len(shown) > 8:
                    tail += ' …'
            return None, "배운 마법에 '%s' 없음 (읽은 마법 %d개%s)" % (spell, len(shown), tail)

        chains = self.mem.cfg.get('chains') or {}
        if chains.get('hotkey_names') == None or chains.get('hotkey_flags') == None:
            return None, 'mem.json 에 hotkey_names/hotkey_flags 없음 (옛 mem.json)'
        an = self._addr('hotkey_names')
        af = self._addr('hotkey_flags')
        if an == None or af == None:
            return None, 'mem.json 단축키 체인을 못 읽음'
        names = mr.readmem(self.mem.h, an, HOTKEY_N * HOTKEY_LEN)
        flags = mr.readmem(self.mem.h, af, HOTKEY_N)
        if names == None or flags == None:
            return None, 'mem.json 단축키 체인을 못 읽음'

        avoided = None
        seen    = []
        for idx in range(HOTKEY_N):
            name = names[idx * HOTKEY_LEN:(idx + 1) * HOTKEY_LEN]
            cut  = name.find(b'\x00')
            if cut >= 0:
                name = name[:cut]
            if len(name) == 0 or flags[idx] != 0:
                continue
            exp = self._expand(name)
            seen.append('F%d=%s' % (5 + idx, exp.decode(self.mem.enc, 'ignore')))
            for e, raw, text in ents:
                if samename(exp, raw):
                    if e['ptr'] == wanted['ptr']:
                        key = 'f%d' % (5 + idx)
                        if key in avoid:
                            if avoided == None:
                                avoided = key
                        else:
                            return key, None
                    break
        if avoided != None:
            return None, '다른 기능이 쓰는 키(%s)에만 등록돼 있음' % avoided.upper()
        desc = '마법 칸 없음'
        if len(seen) > 0:
            desc = '마법 칸: ' + ' '.join(seen)
        return None, "'%s' 이(가) 단축키(F5~F12)에 없음 (%s)" % (spell, desc)

    #게임 단축키 줄에서 클릭해 둔 칸의 키. 옛 방식이고 이름으로 못 찾았을 때만 쓴다
    def _selkey(self, avoid):
        sel = self.mem.value('hotkey_sel')
        if sel == None or not 0 <= sel < HOTKEY_N:
            return None
        key = 'f%d' % (5 + sel)
        if key in avoid:
            return None
        af = self._addr('hotkey_flags')
        if af != None:
            flags = mr.readmem(self.mem.h, af, HOTKEY_N)
            if flags != None and flags[sel] != 0:
                return None
        return key

    #spell = 시전할 마법 이름. avoid = 누르면 안 되는 키 이름들 (호출한 쪽이 전역 단축키로 쓰는 키)
    def cast(self, target_id, ent_ptr, spell, avoid=()):
        key = None
        if self.mem == None or self.mem.h == None:
            return {'state': 'error', 'key': key, 'msg': '게임에 안 붙음'}

        note = ''
        key, msg = self._findkey(spell, avoid)
        if key == None:
            key = self._selkey(avoid)
            if key == None:
                return {'state': 'error', 'key': None, 'msg': msg}
            note = ' | 이름으로 못 찾아 선택된 칸을 누름: ' + msg

        #키 입력이 다른 창으로 가는 것을 막는다
        if mr.frontpid() != self.mem.pid:
            return {'state': 'nofocus', 'key': key, 'msg': '게임 창이 맨 앞이 아님' + note}

        #엔티티 +0x1A 가 0 이 아니면 클라이언트가 고정 대상을 무시하고 대상 선택 모드로 들어간다
        flag = None
        if ent_ptr:
            flag = mr.readmem(self.mem.h, ent_ptr + 0x1A, 1)
        if flag == None or flag[0] != 0:
            return {'state': 'skip', 'key': key, 'msg': '대상 상태 때문에 건너뜀' + note}

        addr = self._addr('spell_target')
        old  = self.mem.value('spell_target')
        t0   = self.mem.value('hotkey_time')
        r0   = self.mem.value('cast_ready')
        if addr == None or old == None or t0 == None or r0 == None:
            return {'state': 'error', 'key': key, 'msg': 'mem.json 시전 체인을 못 읽음' + note}

        if not self._open():
            return {'state': 'error', 'key': key, 'msg': '쓰기 권한으로 프로세스를 못 엶' + note}

        if not writemem(self.h, addr, struct.pack('<I', int(target_id) & 0xFFFFFFFF)):
            return {'state': 'error', 'key': key, 'msg': '대상 id 쓰기 실패' + note}

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
            return {'state': 'nokey', 'key': key, 'msg': '키 입력이 게임에 안 들어감' + note}
        r1 = self.mem.value('cast_ready')
        if r1 != None and r1 != r0:
            return {'state': 'sent', 'key': key, 'msg': '시전됨' + note}
        return {'state': 'nocast', 'key': key, 'msg': '시전 안 됨 (쿨타임/사거리)' + note}
