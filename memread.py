#핏빛서버 클라이언트의 프로세스 메모리를 읽는다
#
#  * 읽기 전용이다. 핸들을 PROCESS_VM_READ | PROCESS_QUERY_INFORMATION 으로만 열고
#    쓰기 함수는 이 파일에 아예 없다. 메모리 변조는 하지 않는다
#  * 오프셋은 코드에 박지 않고 전부 mem.json 에서 읽는다. 사설서버는 패치마다
#    오프셋이 밀리므로, 코드를 고치는 게 아니라 json 만 고쳐서 대응한다
#  * pymem 을 안 쓰고 ctypes 로 직접 부른다. pymem 은 핸들을 PROCESS_ALL_ACCESS 로
#    열어서 권한이 더 필요하고, 우리는 읽기만 하면 되므로 직접 여는 게 낫다
#
#Windows 전용. macOS 에서는 import 자체는 되지만 attach() 가 실패한다
import ctypes
import json
import os
import struct
import sys
import threading

#=====================================================================
# Windows API (ctypes)
#=====================================================================

IS_WIN = sys.platform.startswith('win')

if IS_WIN:
    import ctypes.wintypes as wt
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
else:
    wt  = None
    k32 = None

PROCESS_VM_READ           = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
#QUERY_LIMITED 는 보호된 프로세스에서도 열릴 때가 있어 폴백으로 쓴다
PROCESS_QUERY_LIMITED     = 0x1000

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE   = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

MAX_PATH = 260

#안티치트로 알려진 모듈 이름 조각. 있으면 메모리 읽기가 막힐 가능성이 높다
GUARD_HINTS = ['gameguard', 'npgg', 'npggnt', 'xigncode', 'xhunter',
               'easyanticheat', 'eac', 'battleye', 'beclient', 'nprotect']


if IS_WIN:
    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [('dwSize',              wt.DWORD),
                    ('cntUsage',            wt.DWORD),
                    ('th32ProcessID',       wt.DWORD),
                    ('th32DefaultHeapID',   ctypes.POINTER(ctypes.c_ulong)),
                    ('th32ModuleID',        wt.DWORD),
                    ('cntThreads',          wt.DWORD),
                    ('th32ParentProcessID', wt.DWORD),
                    ('pcPriClassBase',      ctypes.c_long),
                    ('dwFlags',             wt.DWORD),
                    ('szExeFile',           ctypes.c_char * MAX_PATH)]

    class MODULEENTRY32(ctypes.Structure):
        _fields_ = [('dwSize',        wt.DWORD),
                    ('th32ModuleID',  wt.DWORD),
                    ('th32ProcessID', wt.DWORD),
                    ('GlblcntUsage',  wt.DWORD),
                    ('ProccntUsage',  wt.DWORD),
                    ('modBaseAddr',   ctypes.POINTER(ctypes.c_byte)),
                    ('modBaseSize',   wt.DWORD),
                    ('hModule',       wt.HMODULE),
                    ('szModule',      ctypes.c_char * 256),
                    ('szExePath',     ctypes.c_char * MAX_PATH)]


def _needwin():
    if not IS_WIN:
        raise OSError('메모리 읽기는 Windows 에서만 된다 (지금 : ' + sys.platform + ')')


#돌고 있는 프로세스 목록. [(pid, 이름), ...]
def procs():
    _needwin()
    out  = []
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1 or snap == 0:
        return out
    try:
        e = PROCESSENTRY32()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = k32.Process32First(snap, ctypes.byref(e))
        while ok:
            name = e.szExeFile.decode('mbcs', 'ignore')
            out.append((int(e.th32ProcessID), name))
            ok = k32.Process32Next(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


#프로세스가 적재한 모듈 목록. [(이름, 베이스주소, 크기), ...]
#32비트 대상을 64비트 파이썬에서 볼 수 있게 SNAPMODULE32 도 같이 준다
def modules(pid):
    _needwin()
    out  = []
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == -1 or snap == 0:
        return out
    try:
        e = MODULEENTRY32()
        e.dwSize = ctypes.sizeof(MODULEENTRY32)
        ok = k32.Module32First(snap, ctypes.byref(e))
        while ok:
            name = e.szModule.decode('mbcs', 'ignore')
            base = ctypes.cast(e.modBaseAddr, ctypes.c_void_p).value or 0
            out.append((name, int(base), int(e.modBaseSize)))
            ok = k32.Module32Next(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


#안티치트로 보이는 모듈이 있으면 이름 목록을 돌려준다
def guards(pid):
    found = []
    for name, base, size in modules(pid):
        low = name.lower()
        for hint in GUARD_HINTS:
            if hint in low:
                found.append(name)
                break
    return found


#프로세스를 읽기 권한으로만 연다. 실패하면 (None, 윈도우에러번호)
def openproc(pid):
    _needwin()
    for access in (PROCESS_VM_READ | PROCESS_QUERY_INFORMATION,
                   PROCESS_VM_READ | PROCESS_QUERY_LIMITED,
                   PROCESS_VM_READ):
        h = k32.OpenProcess(access, False, int(pid))
        if h:
            return int(h), 0
    return None, ctypes.get_last_error()


def closeproc(h):
    if IS_WIN and h:
        k32.CloseHandle(wt.HANDLE(h))


#대상이 32비트인지. (32비트여부, 판정근거문자열)
def is32(h):
    _needwin()
    wow = ctypes.c_int(0)
    if not k32.IsWow64Process(wt.HANDLE(h), ctypes.byref(wow)):
        return None, 'IsWow64Process 실패'
    if wow.value:
        return True, 'WOW64 (64비트 윈도우에서 도는 32비트 프로세스)'
    #WOW64 가 아니면 OS 와 같은 비트수다
    if ctypes.sizeof(ctypes.c_void_p) == 4:
        return True, '32비트 윈도우'
    return False, '네이티브 64비트'


#실제 읽기. 실패하면 None (부분 읽기도 실패로 본다)
def readmem(h, addr, size):
    if not IS_WIN or not h or size <= 0:
        return None
    if addr <= 0:
        return None
    buf  = ctypes.create_string_buffer(size)
    got  = ctypes.c_size_t(0)
    okay = k32.ReadProcessMemory(wt.HANDLE(h), ctypes.c_void_p(int(addr)),
                                 buf, ctypes.c_size_t(size), ctypes.byref(got))
    if not okay or got.value != size:
        return None
    return buf.raw


#=====================================================================
# mem.json
#=====================================================================

#'0x1A2B' / '0x1a2b' / 6699 / '6699' 을 전부 int 로
def num(v, default=None):
    if v == None:
        return default
    if isinstance(v, int):
        return v
    try:
        return int(str(v).strip(), 0)
    except (TypeError, ValueError):
        return default


#type 이름 -> (struct 포맷, 바이트수)
FMT = {'u8':  ('<B', 1), 'i8':  ('<b', 1),
       'u16': ('<H', 2), 'i16': ('<h', 2),
       'u32': ('<I', 4), 'i32': ('<i', 4),
       'u64': ('<Q', 8), 'i64': ('<q', 8),
       'f32': ('<f', 4), 'f64': ('<d', 8)}


def _unpack(kind, raw, off, enc):
    if kind == 'str':
        chunk = raw[off:]
        cut   = chunk.find(b'\x00')
        if cut >= 0:
            chunk = chunk[:cut]
        return chunk.decode(enc, 'ignore').strip()
    fmt, size = FMT[kind]
    return struct.unpack_from(fmt, raw, off)[0]


DEFAULT_PATH = 'mem.json'


class Mem(object):
    def __init__(self, path=None, logfn=None):
        self.path   = path if path else DEFAULT_PATH
        self.log    = logfn if logfn else (lambda s: None)
        self.cfg    = None
        self.err    = None      #마지막 실패 사유. 로그를 한 번만 찍는 데 쓴다
        self.h      = None
        self.pid    = None
        self.base   = 0         #기준 모듈의 베이스 주소
        self.ptrsz  = 4
        self.enc    = 'cp949'
        self.fail   = 0         #연속 실패 횟수
        self.stale  = False     #True 면 메모리 감지를 포기하고 폴백
        self.lock   = threading.Lock()   #타이머 스레드와 매크로 스레드가 같이 쓴다

    #--- 설정 ---

    def loadcfg(self):
        if not os.path.isfile(self.path):
            self.err = 'mem.json 없음 : ' + self.path
            return False
        try:
            f = open(self.path, 'r', encoding='utf-8')
            self.cfg = json.load(f)
            f.close()
        except Exception as e:
            self.err = 'mem.json 읽기 실패 : ' + str(e)
            return False
        self.enc = str(self.cfg.get('encoding', 'cp949'))
        return True

    #--- 붙기 / 떼기 ---

    #클라이언트에 붙는다. 성공하면 True. 실패 사유는 self.err
    def attach(self):
        if self.cfg == None and not self.loadcfg():
            return False

        want = str(self.cfg.get('process', '')).lower()
        if want == '':
            self.err = 'mem.json 의 process 가 비어 있다'
            return False

        hit = [(pid, name) for pid, name in procs() if name.lower() == want]
        if len(hit) == 0:
            self.err = '프로세스를 못 찾음 : ' + want
            return False
        if len(hit) > 1:
            self.log('같은 이름 프로세스가 ' + str(len(hit)) + '개 - 첫 번째(PID '
                     + str(hit[0][0]) + ')에 붙는다')

        pid    = hit[0][0]
        h, ec  = openproc(pid)
        if h == None:
            self.err = ('OpenProcess 실패 (PID ' + str(pid) + ', 에러 ' + str(ec) + ')'
                        + ' - 관리자 권한으로 실행했는지, 안티치트가 막는지 확인')
            return False

        small, why = is32(h)
        if small == None:
            closeproc(h)
            self.err = why
            return False
        self.ptrsz = 4 if small else 8

        #파이썬 비트수와 대상 비트수가 다르면 주소가 안 맞을 수 있다
        pybits = 64 if ctypes.sizeof(ctypes.c_void_p) == 8 else 32
        tgtbits = 32 if small else 64
        if pybits != tgtbits:
            self.log('경고 : 파이썬 ' + str(pybits) + '비트 / 대상 ' + str(tgtbits)
                     + '비트. 같은 비트수 파이썬으로 돌리는 게 안전하다')

        modname = str(self.cfg.get('module', want)).lower()
        base    = 0
        for name, b, size in modules(pid):
            if name.lower() == modname:
                base = b
                break
        if base == 0:
            closeproc(h)
            self.err = '기준 모듈을 못 찾음 : ' + modname
            return False

        self.h     = h
        self.pid   = pid
        self.base  = base
        self.fail  = 0
        self.stale = False
        self.err   = None
        self.log('메모리 붙음 : ' + want + ' PID ' + str(pid)
                 + ', ' + modname + ' 베이스 0x%X' % base
                 + ', ' + str(tgtbits) + '비트')
        return True

    def detach(self):
        with self.lock:
            if self.h:
                closeproc(self.h)
            self.h    = None
            self.pid  = None
            self.base = 0

    def attached(self):
        return self.h != None

    #읽기가 계속 실패하면 메모리 감지를 포기한다. 로그는 한 번만 찍는다
    #(2초 주기 감시에서 매번 찍으면 GUI 로그가 쓸모없어진다)
    def _bad(self, why, limit):
        self.fail += 1
        if self.fail >= limit and not self.stale:
            self.stale = True
            self.log('메모리 읽기 실패가 ' + str(self.fail) + '회 연속 - 이미지 폴백으로 전환'
                     + ('  (' + why + ')' if why else ''))
        return None

    def _good(self):
        self.fail = 0

    #--- 주소 해석 ---

    #포인터 한 칸 읽기
    def _ptr(self, addr):
        raw = readmem(self.h, addr, self.ptrsz)
        if raw == None:
            return None
        val = struct.unpack('<I' if self.ptrsz == 4 else '<Q', raw)[0]
        #null 이나 명백히 말이 안 되는 주소는 더 따라가지 않는다
        #잘못된 주소를 계속 타고 가서 엉뚱한 값을 읽는 게 제일 나쁜 결과다
        if val < 0x10000:
            return None
        if self.ptrsz == 4 and val > 0xFFFFFFF0:
            return None
        return val

    #체인 하나를 최종 주소까지 따라간다. 규약은 CheatEngine 과 같다 :
    #  offsets 가 비면            -> 모듈베이스 + base            (static)
    #  offsets = [a, b, c] 면      -> [[[모듈베이스+base] + a] + b] + c
    #  (마지막 오프셋은 더하기만 하고 역참조하지 않는다. 그 자리에 값이 있다)
    def resolve(self, spec):
        if self.h == None or spec == None:
            return None
        rva = num(spec.get('base'))
        if rva == None:
            return None
        addr = self.base + rva

        offs = spec.get('offsets') or []
        if len(offs) == 0:
            return addr

        addr = self._ptr(addr)          #첫 역참조
        if addr == None:
            return None
        for raw in offs[:-1]:
            step = num(raw, 0)
            addr = self._ptr(addr + step)
            if addr == None:
                return None
        return addr + num(offs[-1], 0)

    #--- 값 읽기 ---

    #mem.json 의 chains 에서 이름으로 하나 읽는다. 실패하면 None
    def value(self, name):
        if self.h == None or self.cfg == None:
            return None
        spec = (self.cfg.get('chains') or {}).get(name)
        if spec == None:
            return None
        kind = str(spec.get('type', 'u32'))
        with self.lock:
            addr = self.resolve(spec)
            if addr == None:
                return None
            size = num(spec.get('len'), 64) if kind == 'str' else FMT[kind][1]
            raw  = readmem(self.h, addr, size)
        if raw == None:
            return None
        try:
            return _unpack(kind, raw, 0, self.enc)
        except Exception:
            return None

    #여러 개를 한 번에. 하나라도 못 읽으면 그 키는 None
    def values(self, names):
        return dict((n, self.value(n)) for n in names)

    #--- HP / MP ---

    #(현재, 최대) 를 돌려준다. 값이 상식에서 벗어나면 (None, None)
    #  - 오프셋이 밀리면 쓰레기 값이 나온다. 그걸 그대로 믿고 행동하는 게 최악이므로
    #    말이 안 되는 값은 '못 읽었다' 로 처리해서 폴백으로 보낸다
    def _pair(self, cur_key, max_key, cap):
        cur = self.value(cur_key)
        mx  = self.value(max_key)
        if cur == None or mx == None:
            return None, None
        if not isinstance(cur, int) or not isinstance(mx, int):
            return None, None
        if mx <= 0 or mx > cap:
            return None, None
        if cur < 0 or cur > mx:
            return None, None
        return cur, mx

    def _cap(self, key, default):
        return num((self.cfg.get('sane') or {}).get(key), default)

    #HP 비율(0~100). 못 읽으면 None
    def hppct(self):
        cur, mx = self._pair('hp', 'hp_max', self._cap('hp_max', 1000000))
        if cur == None:
            return self._bad('hp', self._cap('fail_limit', 3))
        self._good()
        return cur * 100.0 / mx

    #MP 비율(0~100). 못 읽으면 None
    def mppct(self):
        cur, mx = self._pair('mp', 'mp_max', self._cap('mp_max', 1000000))
        if cur == None:
            return None         #MP 는 없는 서버도 있으니 실패를 카운트하지 않는다
        return cur * 100.0 / mx

    #내 월드 좌표 (x, y). 못 읽으면 None
    def selfpos(self):
        x = self.value('self_x')
        y = self.value('self_y')
        if not isinstance(x, int) or not isinstance(y, int):
            return None
        lo, hi = 0, self._cap('coord_max', 0xFFFF)
        if not (lo <= x <= hi and lo <= y <= hi):
            return None
        return (x, y)

    def selfid(self):
        v = self.value('self_id')
        return v if isinstance(v, int) else None

    #--- 객체 목록 ---

    #주변 객체 전부. [{id, type, x, y, hp, name, clan}, ...]
    #목록을 한 번에 읽고 파이썬에서 쪼갠다 (원소마다 ReadProcessMemory 를 부르면 느리다)
    def objects(self):
        if self.h == None or self.cfg == None:
            return []
        spec = self.cfg.get('objlist')
        if spec == None:
            return []

        fields = spec.get('fields') or {}
        if len(fields) == 0:
            return []
        stride = num(spec.get('stride'), 0)
        if stride <= 0:
            return []

        count = num(spec.get('count'), 0)
        cntch = spec.get('count_chain')
        kind  = str(spec.get('kind', 'array'))

        with self.lock:
            head = self.resolve(spec)
            if head == None:
                return []

            #유효 개수를 따로 읽을 수 있으면 그걸 쓴다 (전체를 다 훑지 않아도 된다)
            if cntch != None:
                got = self.resolve(cntch)
                if got != None:
                    raw = readmem(self.h, got, 4)
                    if raw != None:
                        live = struct.unpack('<I', raw)[0]
                        if 0 < live <= count:
                            count = live
            if count <= 0:
                return []

            if kind == 'linked':
                return self._walk(head, spec, fields, stride, count)

            blob = readmem(self.h, head, stride * count)

        if blob == None:
            self._bad('objlist', self._cap('fail_limit', 3))
            return []
        self._good()

        out = []
        for i in range(count):
            obj = self._parse(blob, i * stride, fields)
            if obj != None:
                out.append(obj)
        return out

    #연결 리스트형 목록. next 포인터를 stride 오프셋에서 읽어 따라간다
    def _walk(self, head, spec, fields, stride, limit):
        out  = []
        node = head
        seen = set()
        size = num(spec.get('node_size'), stride + self.ptrsz)
        while node != None and len(out) < limit:
            if node in seen:        #순환이면 끊는다
                break
            seen.add(node)
            raw = readmem(self.h, node, size)
            if raw == None:
                break
            obj = self._parse(raw, 0, fields)
            if obj != None:
                out.append(obj)
            try:
                nxt = struct.unpack_from('<I' if self.ptrsz == 4 else '<Q', raw, stride)[0]
            except Exception:
                break
            node = nxt if nxt >= 0x10000 else None
        return out

    #원소 하나 해석. id 가 0 이면 빈 칸으로 보고 버린다
    def _parse(self, raw, off, fields):
        obj = {}
        for key, f in fields.items():
            kind = str(f.get('type', 'u32'))
            at   = off + num(f.get('off'), 0)
            if kind == 'str':
                end = at + num(f.get('len'), 32)
            else:
                end = at + FMT[kind][1]
            if at < 0 or end > len(raw):
                return None
            try:
                obj[key] = _unpack(kind, raw, at, self.enc)
            except Exception:
                return None
        if obj.get('id', 1) == 0:
            return None
        return obj

    #객체 중 몹만 / 플레이어만
    def _oftype(self, objs, listkey):
        want = (self.cfg.get('objlist') or {}).get(listkey)
        if not want:
            return []
        want = set(num(v, -1) for v in want)
        return [o for o in objs if o.get('type') in want]

    def mobs(self, objs=None):
        return self._oftype(objs if objs != None else self.objects(), 'mob_types')

    def players(self, objs=None):
        return self._oftype(objs if objs != None else self.objects(), 'player_types')

    #--- 월드 -> 스크린 ---

    #저장된 변환을 (행렬, 원점) 으로. 없거나 깨졌으면 None
    #여러 몹을 한꺼번에 변환할 때 selfpos() 를 몹마다 다시 읽지 않으려고 따로 뺐다
    def screenmat(self):
        sc = self.cfg.get('screen') if self.cfg else None
        if sc == None:
            return None
        m  = sc.get('m')
        og = sc.get('origin')
        if not m or not og or len(m) != 2 or len(og) != 2 or len(m[0]) != 2 or len(m[1]) != 2:
            return None
        return m, og

    #memcalib.py 가 구해 넣은 변환으로 월드 좌표를 화면 좌표로 바꾼다
    #변환이 없으면 None (타일 크기를 추측해서 박지 않는다)
    def toscreen(self, wx, wy):
        got = self.screenmat()
        if got == None:
            return None
        m, og = got
        me = self.selfpos()
        if me == None:
            return None
        dx = wx - me[0]
        dy = wy - me[1]
        try:
            sx = og[0] + m[0][0] * dx + m[0][1] * dy
            sy = og[1] + m[1][0] * dx + m[1][1] * dy
        except (TypeError, IndexError):
            return None
        return (int(round(sx)), int(round(sy)))


#=====================================================================
# 모듈 수준 단일 인스턴스 (pit.py 가 이걸 쓴다)
#=====================================================================

M = None


#mem.json 경로를 주고 인스턴스를 만든다. 이미 있으면 그대로 돌려준다
def init(path, logfn=None):
    global M
    if M == None:
        M = Mem(path, logfn)
    return M
