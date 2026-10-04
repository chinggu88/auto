#메모리 읽기가 가능한지 먼저 가리는 도구 (Phase 0 게이트) + 값 확인용 감시기
#
#  읽기 전용이다. 게임에 키/마우스 입력을 전혀 보내지 않고, 메모리도 쓰지 않는다
#
#쓰는 법 (Windows, 게임을 띄운 상태에서) :
#
#   python memprobe.py --list            돌고 있는 프로세스 전부 (창 제목까지)
#   python memprobe.py --list lin        이름에 'lin' 이 든 것만
#   python memprobe.py --pid 1234        그 PID 로 진단 (mem.json 없어도 된다)
#   python memprobe.py                   mem.json 의 process 로 진단
#
#   python memprobe.py --watch hp,mp              값이 실제로 따라 움직이는지 확인
#   python memprobe.py --watch hp,mp --sec 0.5    감시 주기 바꾸기
#   python memprobe.py --objs                     객체 목록 덤프
#
#주소 찾기 (CheatEngine 없이. 읽기만 하고 게임 메모리에 쓰지 않는다) :
#
#   python memprobe.py --find 2169 --type any --fg    값 하나로 찾기 (타입 자동)
#   python memprobe.py --find 2169,2500 --type any --fg
#                        HP 2169, HP최대 2500 이 가까이 붙어 있는 자리를 찾는다
#   python memprobe.py --next 1900 --fg        맞아서 HP 가 1900 이 됐을 때 좁히기
#   python memprobe.py --next less --fg        값은 모르지만 줄었을 때
#   python memprobe.py --next more --fg        회복해서 늘었을 때
#   python memprobe.py --next same --fg        안 변했을 때
#   python memprobe.py --cands                 지금 남은 후보 보기
#
#   값을 아예 모를 때 (화면에 숫자가 안 보일 때) :
#   python memprobe.py --find unknown --type u32 --fg   지금 상태를 통째로 기록
#   (맞는다) python memprobe.py --next less --fg        줄어든 자리만 남김
#   (또 맞거나 회복) --next less / --next more 를 반복해 좁힌다
#
#   --type any 를 주면 u32/i32/u16/i16/f32 를 전부 시도해 맞는 타입을 알려준다.
#   후보는 scan.dat 에 저장된다. 처음부터 다시 하려면 그 파일을 지운다.
#
#듀얼클라(게임 2창)면 Lin.exe 가 2개라 이름만으로는 구분이 안 된다. 아래 중 하나로 고른다 :
#
#   python memprobe.py --fg              쓸 게임 창을 맨 앞에 두면 3초 뒤 그 창에 붙는다
#   python memprobe.py --pid 17148       PID 를 직접 지정 (--list 로 확인)
#
#   PID 는 게임을 다시 켤 때마다 바뀐다. 정상이고, mem.json 에 적어둘 필요도 없다
#   (mem.json 은 이름으로 찾는다). 어느 쪽 창이냐만 정해주면 된다.
#
#exe 로 묶어 더블클릭하면 압축을 푸느라 몇 초간 까만 창만 보인다. 고장이 아니다.
#출력을 다 읽고 엔터를 눌러야 닫힌다.
#
#판정 : OpenProcess 가 실패하거나 베이스 읽기가 막히면 메모리 방식은 쓸 수 없다.
#       그 경우 main.py 의 이미지 방식을 계속 쓰는 게 맞다
import os
import sys
import time

import memread as mr

#exe 로 묶었을 때도 exe 옆의 mem.json 을 찾도록 memread 의 경로 처리를 쓴다
MEM_PATH, MEM_FOUND, MEM_TRIED = mr.findfile('mem.json')
SCAN_PATH = os.path.join(mr.appdir(), 'scan.dat')


#지금 어느 mem.json 을 쓰는지 항상 보여준다.
#스크립트로 돌릴 때와 exe 로 돌릴 때 파일이 서로 다른 폴더에 있어서,
#엉뚱한 파일을 고쳐놓고 왜 안 되냐고 헤매기 딱 좋다
def saypath():
    if MEM_FOUND:
        say('mem.json : ' + MEM_PATH)
    else:
        say('mem.json 을 못 찾았다. 찾아본 곳 :')
        for t in MEM_TRIED:
            say('    ' + t)
        say('  -> ' + MEM_PATH + ' 에 만들면 된다')


def say(s=''):
    print(s)
    sys.stdout.flush()


#인자 하나를 꺼낸다. --key value 형태. 없으면 default
def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def has(name):
    return name in sys.argv


#--pid <N> / --fg 를 실제 PID 로 바꾼다. 둘 다 없으면 None (= attach 가 알아서 고른다)
#듀얼클라에서 "지금 쓸 창" 을 가리키는 수단이다. PID 는 매번 바뀌므로 저장하지 않는다
def pickpid():
    raw = arg('--pid')
    if raw != None:
        try:
            return int(raw)
        except ValueError:
            say('--pid 는 숫자여야 한다 : ' + str(raw))
            return -1
    if has('--fg'):
        for i in (3, 2, 1):
            say('쓸 게임 창을 클릭해 맨 앞에 두세요... ' + str(i))
            time.sleep(1)
        pid = mr.frontpid()
        if pid == None:
            say('맨 앞 창을 못 찾았다')
            return -1
        t = mr.windows(pid).get(pid, [])
        say('맨 앞 창 : PID ' + str(pid) + '  ' + (' | '.join(t) if t else '(제목 없음)'))
        return pid
    return None


def hexdump(raw, addr, width=16):
    out = []
    for i in range(0, len(raw), width):
        chunk = raw[i:i + width]
        hexs  = ' '.join('%02X' % b for b in chunk)
        text  = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        out.append('  0x%X  %-*s  %s' % (addr + i, width * 3, hexs, text))
    return '\n'.join(out)


#=====================================================================
# 프로세스 목록
#=====================================================================

def dolist(filt):
    rows = mr.procs()
    if filt:
        low  = filt.lower()
        rows = [r for r in rows if low in r[1].lower()]
    rows.sort(key=lambda r: (r[1].lower(), r[0]))

    #같은 이름이 여러 개면(듀얼클라) PID 만으로는 구분이 안 된다.
    #창 제목과 실행 경로까지 같이 찍어서 어느 쪽이 쓸 창인지 가릴 수 있게 한다
    titles = mr.windows()
    dup    = {}
    for pid, name in rows:
        dup[name.lower()] = dup.get(name.lower(), 0) + 1

    say('프로세스 ' + str(len(rows)) + '개' + (" (필터 '" + filt + "')" if filt else ''))
    say()
    for pid, name in rows:
        t = titles.get(pid, [])
        say('  %-8d %-24s %s' % (pid, name, ' | '.join(t) if t else ''))
        #이름이 겹치는 것만 경로까지 보여준다 (전부 찍으면 너무 길다)
        if dup.get(name.lower(), 0) > 1:
            h, ec = mr.openproc(pid)
            if h != None:
                try:
                    p = mr.exepath(h)
                finally:
                    mr.closeproc(h)
                if p:
                    say('  %-8s %s' % ('', p))
    say()

    multi = [n for n, c in dup.items() if c > 1]
    if multi:
        say('같은 이름이 여러 개다 : ' + ', '.join(multi))
        say('  PID 는 실행할 때마다 바뀌므로 mem.json 에 적어두지 않는다.')
        say('  쓸 게임 창을 맨 앞에 두고 --fg 로 돌리거나, --pid <PID> 로 직접 지정한다.')
        say()
    say('클라이언트를 찾았으면 : python memprobe.py --pid <PID>')
    say('  또는 게임 창을 클릭해 맨 앞에 두고 : python memprobe.py --fg')


#PE 헤더를 읽어 ASLR(동적 베이스) 가 켜져 있는지 본다.
#꺼져 있으면 모듈 베이스가 매번 같으므로 주소 작업이 훨씬 쉬워진다
#돌려주는 것 : (ASLR켜짐 True/False/None, 설명)
def aslr(h, base):
    import struct
    raw = mr.readmem(h, base + 0x3C, 4)          #e_lfanew
    if raw == None:
        return None, 'PE 오프셋을 못 읽음'
    pe = base + struct.unpack('<I', raw)[0]

    sig = mr.readmem(h, pe, 4)
    if sig != b'PE\x00\x00':
        return None, 'PE 서명이 아님'

    #COFF 헤더 20바이트 뒤가 옵셔널 헤더. magic 으로 PE32/PE32+ 를 가른다
    magic = mr.readmem(h, pe + 24, 2)
    if magic == None:
        return None, '옵셔널 헤더를 못 읽음'
    m = struct.unpack('<H', magic)[0]
    if m == 0x10B:
        off, kind = 0x46, 'PE32'
    elif m == 0x20B:
        off, kind = 0x46, 'PE32+'
    else:
        return None, '알 수 없는 옵셔널 헤더 magic 0x%X' % m

    raw = mr.readmem(h, pe + 24 + off, 2)        #DllCharacteristics
    if raw == None:
        return None, 'DllCharacteristics 를 못 읽음'
    dll = struct.unpack('<H', raw)[0]
    dyn = bool(dll & 0x0040)                     #IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE
    return dyn, kind + ', DllCharacteristics=0x%04X' % dll


#=====================================================================
# 진단 (Phase 0 게이트)
#=====================================================================

def diag(pid, name, modname):
    say('=' * 66)
    say('진단 대상 : ' + str(name) + '  (PID ' + str(pid) + ')')
    say('=' * 66)
    say()

    #--- 1. 안티치트 모듈 ---
    g = mr.guards(pid)
    if len(g) > 0:
        say('[안티치트] 의심 모듈 발견 : ' + ', '.join(g))
        say('           메모리 읽기가 막힐 가능성이 높다. 아래 OpenProcess 결과를 본다')
    else:
        say('[안티치트] 알려진 모듈 없음')
    say()

    #--- 2. OpenProcess : 이게 핵심 판정 ---
    h, ec = mr.openproc(pid)
    if h == None:
        say('[핸들] OpenProcess 실패 (에러 ' + str(ec) + ')')
        say()
        say('  에러 5   = 접근 거부. 이 스크립트를 관리자 권한으로 다시 돌려본다')
        say('  에러 87  = 잘못된 인자. PID 가 이미 죽었을 수 있다')
        say('  그 외/계속 실패하면 안티치트가 핸들을 막는 것이다')
        say()
        say('판정 : 메모리 방식 불가. main.py 의 이미지 방식을 계속 쓰는 게 맞다')
        return False
    say('[핸들] OpenProcess 성공 (읽기 권한)')

    try:
        #--- 3. 비트수 ---
        small, why = mr.is32(h)
        pybits = 64 if sys.maxsize > 2 ** 32 else 32
        if small == None:
            say('[비트수] 판정 실패 : ' + why)
        else:
            say('[비트수] 대상 ' + ('32' if small else '64') + '비트  (' + why + ')'
                + '  /  파이썬 ' + str(pybits) + '비트')
            if (small and pybits != 32) or ((not small) and pybits != 64):
                say('         ! 비트수가 다르다. 같은 비트수 파이썬으로 돌리는 게 안전하다')
        say()

        #--- 4. 모듈 ---
        mods = mr.modules(pid)
        say('[모듈] ' + str(len(mods)) + '개')
        anchor = None
        for mname, base, size in mods:
            mark = ''
            if modname and mname.lower() == modname.lower():
                mark   = '   <-- mem.json 의 기준 모듈'
                anchor = (mname, base, size)
            say('  %-28s 0x%-12X %10d%s' % (mname, base, size, mark))
        say()

        if anchor == None:
            #기준 모듈 지정이 없으면 exe 본체(보통 첫 번째)를 쓴다
            exe = [m for m in mods if m[0].lower().endswith('.exe')]
            if len(exe) > 0:
                anchor = exe[0]
                say('[기준] mem.json 지정이 없어 exe 본체를 기준으로 본다 : ' + anchor[0])
            elif len(mods) > 0:
                anchor = mods[0]

        if anchor == None:
            say('[읽기] 기준 모듈이 없어 못 해봄')
            say()
            say('판정 : 모듈 목록을 못 읽었다. 비트수 불일치인지 확인한다')
            return False

        #--- 5. 실제 읽기 : 핸들이 열려도 읽기가 막히는 경우를 걸러낸다 ---
        mname, base, size = anchor
        raw = mr.readmem(h, base, 64)
        if raw == None:
            say('[읽기] ReadProcessMemory 실패 (0x%X)' % base)
            say()
            say('판정 : 핸들은 열렸지만 읽기가 막혔다. 메모리 방식 불가')
            return False

        say('[읽기] ' + mname + ' 베이스 0x%X 에서 64바이트 성공' % base)
        say(hexdump(raw, base))
        if raw[:2] == b'MZ':
            say('        앞 2바이트가 MZ = PE 헤더. 제대로 읽고 있다')
        say()

        say('=' * 66)
        say('판정 : 메모리 읽기 가능. 다음 단계로 간다')
        say('=' * 66)
        say()
        dyn, why = aslr(h, base)
        say('다음에 할 일 :')
        say('  1. CheatEngine 등으로 HP / HP최대 주소를 찾는다')
        say('  2. 찾은 값을 ' + mname + ' 베이스(0x%X) 기준 상대값으로 바꾼다' % base)
        say('       상대값 = 절대주소 - 0x%X' % base)
        say('  3. mem.json 의 chains.hp.base 에 그 상대값을 넣는다')
        say('  4. python memprobe.py --watch hp,hp_max 로 값이 따라 움직이는지 확인한다')
        say()
        if dyn is False:
            say('  [ASLR] 꺼져 있다 (' + why + ')')
            say('         베이스가 항상 0x%X 다. 게임을 껐다 켜도 주소가 안 변하므로' % base)
            say('         CheatEngine 에서 찾은 주소를 그대로 믿고 작업하면 된다.')
            say('         그래도 mem.json 에는 상대값으로 적는다 (클라가 바뀌어도 안 깨지게).')
        elif dyn is True:
            say('  [ASLR] 켜져 있다 (' + why + ')')
            say('         게임을 재시작하면 베이스가 바뀐다. 절대주소가 아니라 반드시')
            say('         모듈 기준 상대값으로 적어야 매번 다시 안 찾는다.')
        else:
            say('  [ASLR] 판정 실패 : ' + str(why))
            say('         안전하게 모듈 기준 상대값으로 적는다.')
        return True
    finally:
        mr.closeproc(h)


#=====================================================================
# 값 검색 (CheatEngine 없이 주소를 찾는다)
#   읽기 전용이다. 게임 메모리에 아무것도 쓰지 않는다
#   후보 목록은 scan.dat 에 저장되고, --next 로 계속 좁혀 나간다
#=====================================================================

SCAN_MAGIC = b'MSCAN2\n'


#scan.dat 는 두 가지 모드로 쓴다
#  'C' : 후보 목록 [(주소, 값), ...]           - 값을 알고 찾을 때
#  'S' : 영역 스냅샷 [(시작주소, 그때의 바이트)] - 값을 모르고 '줄었다/늘었다' 로 좁힐 때
def _writehead(f, mode, kind):
    import struct
    f.write(SCAN_MAGIC)
    f.write(mode.encode('ascii'))
    k = kind.encode('ascii')
    f.write(struct.pack('<B', len(k)) + k)


#후보를 타입별로 나눠 저장한다.
#  단일 값 검색에서 타입을 하나로 정해버리면 안 된다 : 2바이트 값은 우연히 더 많이
#  잡히는 게 정상이라 '후보가 적은 타입' 을 고르는 건 근거가 없다.
#  어느 타입이 맞는지는 --next 로 걸러보면 저절로 드러나므로, 전부 들고 간다
def savecands(groups):
    import struct
    groups = [(k, c) for k, c in groups if len(c) > 0]
    with open(SCAN_PATH, 'wb') as f:
        _writehead(f, 'C', 'multi' if len(groups) != 1 else groups[0][0])
        f.write(struct.pack('<I', len(groups)))
        for kind, cands in groups:
            kb = kind.encode('ascii')
            f.write(struct.pack('<B', len(kb)) + kb)
            f.write(struct.pack('<Q', len(cands)))
            for a, v in cands:
                f.write(struct.pack('<Qq', a, v))


#스냅샷은 통째로 메모리에 들고 있으면 수백 MB 라, 읽으면서 바로 파일에 흘려 쓴다
def savesnap(m, kind):
    import struct
    regs = mr.regions(m.h, writable=True,
                      maxaddr=(1 << 32) if m.ptrsz == 4 else None)
    total = sum(r[1] for r in regs)
    say('기록할 영역 %d개, %.1f MB' % (len(regs), total / 1048576.0))
    if total > (1 << 30):
        say('1GB 가 넘는다. 값을 아는 쪽(--find <숫자>)으로 하는 게 낫다')
        return 0

    n = 0
    with open(SCAN_PATH, 'wb') as f:
        _writehead(f, 'S', kind)
        pos = f.tell()
        f.write(struct.pack('<Q', 0))        #영역 수는 나중에 채운다
        for base, size in regs:
            raw = mr.readmem(m.h, base, size)
            if raw == None:
                continue                      #중간에 못 읽는 영역은 건너뛴다
            f.write(struct.pack('<QQ', base, size))
            f.write(raw)
            n += 1
        f.seek(pos)
        f.write(struct.pack('<Q', n))
    return n


def loadhead(f):
    import struct
    if f.read(len(SCAN_MAGIC)) != SCAN_MAGIC:
        return None, None
    mode = f.read(1).decode('ascii')
    n    = struct.unpack('<B', f.read(1))[0]
    return mode, f.read(n).decode('ascii')


#돌려주는 것 : (모드, 데이터)
#   'C' -> [(타입, [(주소,값), ...]), ...]      'S' -> 타입 문자열
#   없으면 (None, None)
def loadcands():
    import struct
    if not os.path.isfile(SCAN_PATH):
        return None, None
    try:
        with open(SCAN_PATH, 'rb') as f:
            mode, kind = loadhead(f)
            if mode != 'C':
                return 'S', kind
            ng     = struct.unpack('<I', f.read(4))[0]
            groups = []
            for _ in range(ng):
                n  = struct.unpack('<B', f.read(1))[0]
                k  = f.read(n).decode('ascii')
                cn = struct.unpack('<Q', f.read(8))[0]
                cs = []
                for _ in range(cn):
                    cs.append(struct.unpack('<Qq', f.read(16)))
                groups.append((k, cs))
        return 'C', groups
    except Exception as e:
        say('scan.dat 읽기 실패 : ' + str(e))
        return None, None


#스냅샷과 지금 메모리를 비교해 조건에 맞는 자리만 후보로 만든다.
#1억 개가 넘는 비교라 파이썬 루프로는 불가능하다. numpy 로 통째로 비교한다
def snapnarrow(m, kind, how):
    import struct
    try:
        import numpy
    except ImportError:
        say('이 방식에는 numpy 가 필요하다 : pip install numpy')
        return None

    NP = {'u8': 'u1', 'i8': 'i1', 'u16': 'u2', 'i16': 'i2',
          'u32': 'u4', 'i32': 'i4', 'u64': 'u8', 'i64': 'i8',
          'f32': 'f4', 'f64': 'f8'}
    if kind not in NP:
        say(kind + ' 타입은 이 방식으로 못 쓴다')
        return None
    dt   = numpy.dtype('<' + NP[kind])
    size = dt.itemsize

    out = []
    with open(SCAN_PATH, 'rb') as f:
        mode, _ = loadhead(f)
        nreg = struct.unpack('<Q', f.read(8))[0]
        for _ in range(nreg):
            base, rsize = struct.unpack('<QQ', f.read(16))
            old = f.read(rsize)
            new = mr.readmem(m.h, base, rsize)
            if new == None:
                continue
            cnt = rsize // size
            if cnt == 0:
                continue
            a = numpy.frombuffer(old, dtype=dt, count=cnt)
            b = numpy.frombuffer(new, dtype=dt, count=cnt)
            if how == 'less':
                mask = b < a
            elif how == 'more':
                mask = b > a
            elif how == 'same':
                mask = b == a
            elif how == 'changed':
                mask = b != a
            elif how == 'notless':
                mask = b >= a
            elif how == 'notmore':
                mask = b <= a
            else:
                try:
                    want = int(how, 0)
                except ValueError:
                    say('--next 는 숫자 또는 less / more / same / changed 다 : ' + how)
                    return None
                mask = b == want
            idx = numpy.nonzero(mask)[0]
            for i in idx:
                out.append((base + int(i) * size, int(b[i])))
            if len(out) > 3000000:
                say('아직 후보가 300만 개가 넘는다. 조건을 더 걸어 좁힌다')
                break
    return out


#'u32' -> (struct 포맷, 바이트수, 정렬)
def kindinfo(kind):
    fmt, size = mr.FMT[kind]
    return fmt, size, size


#메모리를 한 번 훑어 value 가 있는 자리를 전부 찾는다.
#pair 가 있으면 'value 에서 win 바이트 안(앞뒤 모두)에 pair 도 있는' 자리만 남긴다.
#  - 앞뒤를 다 보는 이유 : hp_max 가 hp 보다 앞에 놓인 구조체도 흔하다
#돌려주는 것 : (짝까지 맞는 후보, 값만 맞는 자리 수, [관찰된 간격들])
#  '값만 맞는 자리 수' 가 있어야 "값이 아예 없다" 와 "짝이 안 붙어 있다" 를 구분해준다
def scanall(m, kind, value, pair=None, win=64, quiet=False):
    import struct
    fmt, size, align = kindinfo(kind)
    try:
        needle = struct.pack(fmt, value)
    except struct.error:
        return None, 0, []

    pneedle = None
    if pair != None:
        try:
            pneedle = struct.pack(fmt, pair)
        except struct.error:
            return None, 0, []

    regs  = mr.regions(m.h, writable=True,
                       maxaddr=(1 << 32) if m.ptrsz == 4 else None)
    if not quiet:
        total = sum(r[1] for r in regs)
        say('검색 영역 %d개, %.1f MB' % (len(regs), total / 1048576.0))

    cands  = []
    single = 0
    gaps   = []
    for base, size_r in regs:
        for at, raw in mr.readchunks(m.h, base, size_r):
            pos = raw.find(needle)
            while pos >= 0:
                addr = at + pos
                if addr % align == 0:
                    single += 1
                    if pneedle == None:
                        cands.append((addr, value))
                    else:
                        #뒤쪽을 먼저 본다 (hp 다음에 hp_max 가 오는 쪽이 더 흔하다)
                        got = None
                        tail = raw[pos + size: pos + size + win]
                        q = tail.find(pneedle)
                        while q >= 0:
                            if (addr + size + q) % align == 0:
                                got = size + q
                                break
                            q = tail.find(pneedle, q + 1)
                        if got == None:
                            lo   = max(0, pos - win)
                            head = raw[lo: pos]
                            q = head.find(pneedle)
                            while q >= 0:
                                a2 = at + lo + q
                                if a2 % align == 0:
                                    got = a2 - addr      #음수 = 짝이 앞에 있다
                                    break
                                q = head.find(pneedle, q + 1)
                        if got != None:
                            cands.append((addr, value))
                            gaps.append(got)
                pos = raw.find(needle, pos + 1)
                if len(cands) > 2000000:
                    if not quiet:
                        say('후보가 너무 많다(200만 초과). 더 특이한 값으로 다시 찾는다')
                    return None, single, gaps
    return cands, single, gaps


#타입을 모를 때 쓸 후보 타입들. 구버전 클라이언트는 2바이트인 경우가 흔하다
ANYTYPES = ['u32', 'i32', 'u16', 'i16', 'f32']


#이미 있는 후보만 다시 읽어 좁힌다. how : 숫자 / less / more / same / changed
#돌려주는 것 : (살아남은 후보, 비교표[(주소, 이전값, 현재값)])
#  비교표가 있어야 0개가 됐을 때 '왜' 를 보여줄 수 있다
def narrow(m, kind, cands, how):
    import struct
    fmt, size, align = kindinfo(kind)
    want = None
    if how not in ('less', 'more', 'same', 'changed', 'notless', 'notmore'):
        try:
            want = int(how, 0)
        except ValueError:
            say('--next 는 숫자 또는 less / more / same / changed /'
                ' notless / notmore 다 : ' + how)
            return None, None

    out   = []
    table = []
    for addr, old in cands:
        raw = mr.readmem(m.h, addr, size)
        if raw == None:
            table.append((addr, old, None))
            continue
        cur = struct.unpack(fmt, raw)[0]
        table.append((addr, old, cur))
        if want != None:
            if cur == want:
                out.append((addr, cur))
        elif how == 'less' and cur < old:
            out.append((addr, cur))
        elif how == 'more' and cur > old:
            out.append((addr, cur))
        elif how == 'same' and cur == old:
            out.append((addr, cur))
        elif how == 'changed' and cur != old:
            out.append((addr, cur))
        #notless = '줄지 않았다'. 매초 알아서 줄어드는 타이머/카운터를 걸러내는 데 쓴다.
        #HP 는 맞지 않으면 그대로이거나(정지) 늘어난다(재생). 타이머는 계속 준다
        elif how == 'notless' and cur >= old:
            out.append((addr, cur))
        elif how == 'notmore' and cur <= old:
            out.append((addr, cur))
    return out, table


#후보를 보여준다. 적어지면 mem.json 에 그대로 붙여 넣을 줄까지 만들어 준다
#groups = [(타입, [(주소,값), ...]), ...]
def showcands(m, groups, limit=30):
    cands = [(a, v, k) for k, cs in groups for a, v in cs]
    kind  = groups[0][0] if len(groups) == 1 else 'u32'
    say()
    if len(groups) > 1:
        say('남은 후보 : ' + str(len(cands)) + '개  ('
            + ', '.join('%s %d개' % (k, len(c)) for k, c in groups) + ')')
    else:
        say('남은 후보 : ' + str(len(cands)) + '개')
    if len(cands) == 0:
        say()
        say('  너무 많이 좁혔다. 조건이 틀렸을 가능성이 크다.')
        say('  (예: 안 줄었는데 --next less 를 했거나, HP 숫자를 잘못 읽었거나)')
        say('  scan.dat 를 지우고 --find 부터 다시 한다 :')
        say('      del scan.dat')
        say('      python memprobe.py --find <지금 HP> --type any')
        return

    if len(cands) > limit:
        say('  (앞 %d개만 표시)' % limit)
    say()
    say('  %-18s %-6s %-12s %s' % ('절대주소', '타입', '값', 'mem.json 에 넣을 base'))
    for addr, val, k in cands[:limit]:
        rva = addr - m.base
        mark = '0x%X' % rva if 0 <= rva < (1 << 32) else '(모듈 밖 - 포인터 필요)'
        say('  0x%-16X %-6s %-12d %s' % (addr, k, val, mark))

    #--- 다음에 칠 명령을 그대로 보여준다 ---
    #'--next <새값>' 처럼 빈칸으로 두면 뭘 쳐야 할지 알 수가 없다. 통째로 찍어준다
    say()
    say('=' * 66)
    if len(cands) > 3:
        say('아직 후보가 많다. 게임에서 HP 를 바꿔서 더 좁힌다')
        say('=' * 66)
        say()
        say('  1) 몹한테 맞아서 HP 를 떨어뜨린다')
        say('  2) 바뀐 HP 숫자를 읽고 아래 중 하나를 친다 :')
        say()
        say('       새 HP 가 예를 들어 1850 이면')
        say('           python memprobe.py --next 1850')
        say()
        say('       숫자를 못 읽겠으면 (줄어든 것만 남기기)')
        say('           python memprobe.py --next less')
        say()
        say('  3) 후보가 3개 이하로 줄 때까지 1~2 를 반복한다')
        say('     (회복했을 때는 --next more, 안 변했을 때는 --next same)')
        return

    say('후보가 거의 다 좁혀졌다')
    say('=' * 66)
    say()
    say('마지막 확인 : HP 를 한 번 더 바꾸고 아래를 쳐서 살아남는지 본다')
    say('    python memprobe.py --next less        (맞아서 줄었을 때)')
    say('    python memprobe.py --next more        (회복해서 늘었을 때)')
    say()
    say('살아남으면 mem.json 의 chains 를 이렇게 고친다 :')
    say()
    a, v, k = cands[0]
    rva  = a - m.base
    say('    "hp":     { "base": "0x%X", "offsets": [], "type": "%s" },' % (rva, k))
    if len(cands) > 1:
        b = cands[1][0] - m.base
        say('    "hp_max": { "base": "0x%X", "offsets": [], "type": "%s" },'
            % (b, cands[1][2]))
        say('')
        say('  (hp 와 hp_max 중 어느 쪽이 어느 쪽인지는 --watch 로 보면 바로 안다.')
        say('   맞을 때 변하는 쪽이 hp, 안 변하는 쪽이 hp_max 다)')
    else:
        say('')
        say('  hp_max 는 보통 hp 바로 옆에 있다. --watch 로 hp 를 확인한 뒤')
        say('  그 주소에서 ±2, ±4 한 값을 hp_max 로 넣어보면 대개 맞는다')
    say()
    say('고친 파일 위치 : ' + MEM_PATH)
    say()
    say('다 적었으면 값이 따라 움직이는지 본다 :')
    say('    python memprobe.py --watch hp,hp_max')


def dofind(pid, kind, spec):
    m = mr.Mem(MEM_PATH, say)
    if not m.attach(pid):
        say('붙기 실패 : ' + str(m.err))
        return
    try:
        #--- 값을 모를 때 : 지금 상태를 통째로 기록해두고 나중에 비교한다 ---
        if spec.strip().lower() in ('unknown', '?'):
            k = 'u32' if kind == 'any' else kind
            say('값을 모르는 채로 시작한다. 지금 메모리를 기록해 둔다 (' + k + ')')
            say()
            t0 = time.time()
            n  = savesnap(m, k)
            if n == 0:
                return
            say('영역 %d개 기록 완료 (%.1f초)' % (n, time.time() - t0))
            say()
            say('이제 게임에서 HP 를 바꾸고 아래처럼 좁혀 간다 :')
            say('    맞아서 줄었으면   python memprobe.py --next less --fg')
            say('    회복해서 늘었으면 python memprobe.py --next more --fg')
            say('    안 변했으면       python memprobe.py --next same --fg')
            return

        pair = None
        if ',' in spec:
            a, b = spec.split(',', 1)
            value, pair = int(a.strip(), 0), int(b.strip(), 0)
        else:
            value = int(spec.strip(), 0)

        kinds = ANYTYPES if kind == 'any' else [kind]
        if pair != None:
            say('값 %d 와 %d 가 %d바이트 안에 같이 있는 자리를 찾는다' % (value, pair, 64))
            say('  HP 와 HP최대는 구조체 안에서 붙어 있으므로 둘을 같이 주면 확 줄어든다')
            say('  (앞뒤 양쪽을 다 본다. hp_max 가 앞에 오는 구조체도 있다)')
        else:
            say('값 %d 를 찾는다' % value)
        say('타입 : ' + (', '.join(kinds) + '  (전부 시도)' if len(kinds) > 1 else kinds[0]))
        say()

        t0      = time.time()
        results = {}
        for k in kinds:
            cands, single, gaps = scanall(m, k, value, pair, quiet=(k != kinds[0]))
            if cands == None:
                continue
            results[k] = (cands, single, gaps)
            if len(kinds) > 1:
                say('  %-4s : 값만 맞는 자리 %d개  /  짝까지 맞는 자리 %d개'
                    % (k, single, len(cands)))
        say('걸린 시간 %.1f초' % (time.time() - t0))

        #타입을 하나로 정하지 않는다. 어느 타입이 맞는지는 --next 로 걸러보면
        #저절로 드러난다. 여기서 버리면 정작 맞는 타입을 날려버릴 수 있다
        #(u16 은 우연히 더 많이 잡히는 게 정상이라 '적은 쪽' 을 고르면 안 된다)
        order  = dict((k, i) for i, k in enumerate(ANYTYPES))
        groups = [(k, results[k][0]) for k in kinds
                  if k in results and len(results[k][0]) > 0]
        groups.sort(key=lambda g: order.get(g[0], 99))
        if len(groups) == 0:
            explainzero(m, value, pair, results, kinds)
            return

        allgaps = [g for k, (c, sg, gp) in results.items() for g in gp]
        if allgaps:
            uniq = sorted(set(allgaps))[:6]
            say('짝까지의 간격 : ' + ', '.join(('%+d' % g) for g in uniq) + ' 바이트'
                + '   (음수면 짝이 앞에 있다는 뜻)')

        savecands(groups)
        showcands(m, groups)
    finally:
        m.detach()


#아무것도 못 찾았을 때, 왜 못 찾았는지 갈라서 알려준다.
#'0개' 라고만 하면 값이 없는 건지 짝이 안 붙은 건지 타입이 틀린 건지 알 수가 없다
def explainzero(m, value, pair, results, kinds):
    say()
    say('=' * 66)
    say('찾은 자리가 없다')
    say('=' * 66)
    say()

    anysingle = [(k, sg) for k, (c, sg, g) in results.items() if sg > 0]
    if pair != None and anysingle:
        say('값 %d 자체는 메모리에 있다 :' % value)
        for k, sg in anysingle:
            say('    %-4s 로 %d군데' % (k, sg))
        say()
        say('즉 "값이 없는" 게 아니라 "%d 와 %d 가 서로 가까이 있지 않다" 는 뜻이다.'
            % (value, pair))
        say('HP 와 HP최대가 떨어져 있는 구조체인 것 같다. 짝을 빼고 단일 값으로 찾는다 :')
        say()
        say('    python memprobe.py --find %d --type any --fg' % value)
        say()
        say('그 다음 게임에서 HP 를 바꾸고 --next 로 좁히면 된다.')
        return

    say('값 %d 가 어떤 타입으로도 안 나온다. 가능한 이유 :' % value)
    say()
    say('  1. 화면에 보이는 숫자와 메모리에 든 값이 다르다')
    say('     - HP 가 소수점으로 저장되는 클라이언트도 있다 -> --type f32 로도 해본다')
    say('     - 표시값이 계산 결과일 수 있다 (예: 백분율에서 역산)')
    say('  2. 값이 자주 바뀌어 스캔 도중 달라졌다')
    say('     - 안전한 곳에서 HP 가 멈춰 있을 때 다시 해본다')
    say('  3. 숫자를 잘못 읽었다 (최대치/현재치 혼동 등)')
    say()
    say('값을 모를 때 쓰는 방법도 있다. 아래처럼 "변했다/줄었다" 로 좁혀 간다 :')
    say()
    say('    python memprobe.py --find unknown --type u32 --fg     (현재 상태 기록)')
    say('    (게임에서 맞는다)')
    say('    python memprobe.py --next less --fg                   (줄어든 것만 남김)')
    say('    (또 맞거나 회복한다)')
    say('    python memprobe.py --next less --fg   또는 --next more --fg')
    say()
    say('  몇 번 반복하면 후보가 몇 개로 줄어든다.')


#좁혔더니 0개가 됐을 때, 후보들이 실제로 어떤 값이었는지 보여준다.
#이게 없으면 "0개" 만 보고 같은 짓을 반복하게 된다.
#전부 '그대로' 면 HP 가 안 변했거나 그 자리들이 HP 가 아니라는 뜻이고,
#'늘었다' 면 less 가 아니라 more 를 써야 한다는 뜻이다
def dumpcompare(m, tables, how, limit=16):
    rows = [(k, a, o, c) for k, t in tables for a, o, c in t]
    if len(rows) == 0:
        return
    say()
    say('후보들이 지금 실제로 어떤 값인지 :')
    say()
    say('  %-18s %-6s %-12s %-12s %s' % ('주소', '타입', '이전', '현재', '변화'))
    same = up = down = dead = 0
    for k, a, o, c in rows[:limit]:
        if c == None:
            w, dead = '못 읽음', dead + 1
        elif c == o:
            w, same = '그대로', same + 1
        elif c > o:
            w, up = '늘었다', up + 1
        else:
            w, down = '줄었다', down + 1
        say('  0x%-16X %-6s %-12s %-12s %s'
            % (a, k, o, '--' if c == None else c, w))
    for k, a, o, c in rows[limit:]:
        if c == None:
            dead += 1
        elif c == o:
            same += 1
        elif c > o:
            up += 1
        else:
            down += 1
    if len(rows) > limit:
        say('  ... (전체 %d개)' % len(rows))

    say()
    say('정리 : 그대로 %d개, 늘었다 %d개, 줄었다 %d개, 못 읽음 %d개'
        % (same, up, down, dead))
    say()
    if down > 0 and how != 'less':
        say('-> 줄어든 자리가 있다. python memprobe.py --next less 를 쓴다')
    elif up > 0 and how != 'more':
        say('-> 늘어난 자리가 있다. python memprobe.py --next more 를 쓴다')
    elif same == len(rows):
        say('-> 하나도 안 변했다. 둘 중 하나다 :')
        say('   (1) HP 가 실제로 안 변했다 - 몹한테 맞아서 확실히 줄인 뒤 다시 한다')
        say('   (2) 이 자리들은 HP 가 아니다 - 처음 찾은 값이 HP 가 아니었다는 뜻')
        say()
        say('   (2) 라면 값을 모르는 채로 찾는 방법이 확실하다 :')
        say('       del scan.dat')
        say('       python memprobe.py --find unknown --type u32')
        say('       (몹한테 맞는다)')
        say('       python memprobe.py --next less')
        say('       (또 맞는다)  python memprobe.py --next less   ... 반복')


def donext(pid, how):
    mode, data = loadcands()
    if mode == None:
        say('이전 검색 결과(scan.dat)가 없다. 먼저 --find 로 찾는다')
        return

    m = mr.Mem(MEM_PATH, say)
    if not m.attach(pid):
        say('붙기 실패 : ' + str(m.err))
        return
    try:
        if mode == 'S':
            #스냅샷 모드 : 기록해둔 것과 지금을 통째로 비교한다
            kind = data
            say('기록해둔 메모리와 지금을 비교해 ' + how + ' 인 자리를 찾는다 ('
                + kind + ')')
            t0  = time.time()
            out = snapnarrow(m, kind, how)
            if out == None:
                return
            say('걸린 시간 %.1f초' % (time.time() - t0))
            groups = [(kind, out)]
            savecands(groups)
            showcands(m, groups)
            return

        groups = data
        total  = sum(len(c) for k, c in groups)
        if total == 0:
            say('남은 후보가 없다. scan.dat 를 지우고 --find 부터 다시 한다')
            return
        say('이전 후보 ' + str(total) + '개를 ' + how + ' 로 좁힌다  ('
            + ', '.join('%s %d개' % (k, len(c)) for k, c in groups) + ')')

        out    = []
        tables = []
        for kind, cands in groups:
            kept, table = narrow(m, kind, cands, how)
            if kept == None:
                return
            tables.append((kind, table))
            if len(kept) > 0:
                out.append((kind, kept))

        if len(out) == 0:
            showcands(m, [(groups[0][0], [])])
            dumpcompare(m, tables, how)
            return

        savecands(out)
        showcands(m, out)
    finally:
        m.detach()


def docands(pid):
    mode, data = loadcands()
    if mode == None:
        say('scan.dat 가 없다. 먼저 --find 로 찾는다')
        return
    if mode == 'S':
        say('지금은 "값 모름" 기록 상태다 (' + str(data) + ').')
        say('게임에서 HP 를 바꾸고 --next less / more / same 으로 좁혀야 후보가 생긴다')
        return
    m = mr.Mem(MEM_PATH, say)
    if not m.attach(pid):
        say('붙기 실패 : ' + str(m.err))
        return
    try:
        showcands(m, data)
    finally:
        m.detach()


#=====================================================================
# 값 감시
#=====================================================================

def watch(names, sec, pid):
    m = mr.Mem(MEM_PATH, say)
    if not m.attach(pid):
        say('붙기 실패 : ' + str(m.err))
        return

    #--- 감시 전 점검 ---
    #그냥 돌리면 '--' 만 줄줄이 찍히는데, 그것만으로는 아직 주소를 안 넣은 건지
    #넣었는데 못 읽는 건지 알 수가 없다. 돌기 전에 항목별로 상태를 한 번씩 찍는다
    say()
    say('점검 :')
    DERIVED = ('hp%', 'mp%', 'pos')
    real    = [n for n in names if n not in DERIVED]
    good    = 0
    for n in real:
        okay, why = m.explain(n)
        say('  %-10s %s' % (n, ('OK   ' if okay else '안 됨 ') + why))
        if okay:
            good += 1

    if len(real) > 0 and good == 0:
        say()
        say('=' * 66)
        say('읽을 수 있는 항목이 하나도 없다. 감시를 시작하지 않는다')
        say('=' * 66)
        say()
        blank = [n for n in real
                 if mr.num(((m.cfg.get('chains') or {}).get(n) or {}).get('base')) == None]
        if len(blank) == len(real):
            say('아직 mem.json 에 주소를 안 넣었다. 이 도구는 주소를 "찾아주는" 게 아니라')
            say('이미 넣어둔 주소를 "읽어서 보여주는" 도구다.')
            say()
            say('mem.json 을 메모장으로 열어 chains 를 이렇게 채워야 한다 :')
            say('')
            say('    "hp":     { "base": "0x1234AB", "offsets": [], "type": "u32" },')
            say('    "hp_max": { "base": "0x1234AF", "offsets": [], "type": "u32" },')
            say('')
            say('  base 는 절대주소가 아니라 모듈 베이스(0x%X) 기준 상대값이다 :' % m.base)
            say('      상대값 = CheatEngine 에서 찾은 절대주소 - 0x%X' % m.base)
            say('  type 은 4바이트면 u32, 2바이트면 u16 으로 적는다.')
        say()
        return

    say()
    say('감시 : ' + ', '.join(names) + '   (' + str(sec) + '초 주기, ctrl+c 로 중단)')
    say('게임에서 맞거나 회복하거나 움직이면서 숫자가 따라 움직이는지 본다')
    say()

    #체인에 없는 이름을 적었으면 미리 알려준다
    known = list((m.cfg.get('chains') or {}).keys())
    for n in names:
        if n not in known and n not in DERIVED:
            say("  ! '" + n + "' 는 mem.json 의 chains 에 없다. 아는 것 : "
                + ', '.join(known))

    try:
        while True:
            parts = []
            for n in names:
                if n == 'hp%':
                    v = m.hppct()
                    parts.append('hp% = ' + ('--' if v == None else '%.1f' % v))
                elif n == 'mp%':
                    v = m.mppct()
                    parts.append('mp% = ' + ('--' if v == None else '%.1f' % v))
                elif n == 'pos':
                    v = m.selfpos()
                    parts.append('pos = ' + ('--' if v == None else str(v)))
                else:
                    v = m.value(n)
                    parts.append(n + ' = ' + ('--' if v == None else str(v)))
            say(time.strftime('%H:%M:%S') + '  ' + '   '.join(parts))
            time.sleep(sec)
    except KeyboardInterrupt:
        say()
        say('중단')
    finally:
        m.detach()


#=====================================================================
# 객체 목록 덤프
#=====================================================================

def dumpobjs(limit, pid):
    m = mr.Mem(MEM_PATH, say)
    if not m.attach(pid):
        say('붙기 실패 : ' + str(m.err))
        return
    try:
        me   = m.selfpos()
        mid  = m.selfid()
        objs = m.objects()
        say()
        say('내 좌표 : ' + str(me) + '   내 id : ' + str(mid))
        say('객체 ' + str(len(objs)) + '개' + (' (앞 ' + str(limit) + '개만)'
                                              if len(objs) > limit else ''))
        say()
        if len(objs) == 0:
            say('  비었다. objlist 의 base / stride / count / fields 를 확인한다')
            say('  id 가 0 인 칸은 빈 칸으로 보고 버리므로, id 오프셋이 틀리면 전부 사라진다')
            return

        keys = sorted(objs[0].keys())
        say('  ' + '  '.join('%-12s' % k for k in keys))
        for o in objs[:limit]:
            row = []
            for k in keys:
                v = o.get(k)
                row.append('%-12s' % (str(v)[:12]))
            mark = ''
            if mid != None and o.get('id') == mid:
                mark = '  <-- 나'
            say('  ' + '  '.join(row) + mark)
        say()
        mobs = m.mobs(objs)
        plrs = m.players(objs)
        say('몹 ' + str(len(mobs)) + '마리 / 플레이어 ' + str(len(plrs)) + '명')
        clans = sorted(set(p.get('clan', '') for p in plrs if p.get('clan')))
        if clans:
            say('보이는 혈맹 : ' + ', '.join(clans))
            say('  -> 내 혈맹명을 pit.py 의 혈맹 화이트리스트에 그대로 넣는다')
    finally:
        m.detach()


#=====================================================================

def main():
    #--where 는 경로만 찍으므로 Windows 체크보다 먼저 둔다 (어디서든 쓸 수 있게)
    if has('--where'):
        say('실행 폴더   : ' + mr.appdir())
        say('현재 폴더   : ' + os.getcwd())
        say('scan.dat    : ' + SCAN_PATH)
        saypath()
        return

    if not mr.IS_WIN:
        say('이 도구는 Windows 에서만 된다 (지금 : ' + sys.platform + ')')
        say('게임이 도는 윈도우 PC 에서 돌려야 한다')
        return

    #--list 말고는 전부 mem.json 을 쓰므로 어느 파일인지 먼저 알려준다
    if not has('--list'):
        saypath()
        say()

    if has('--list'):
        dolist(arg('--list'))
        return

    pid = pickpid()
    if pid == -1:            #--pid / --fg 가 잘못됐다
        return

    kind = arg('--type', 'u32')
    if kind != 'any' and kind not in mr.FMT:
        say('--type 은 any 또는 ' + ', '.join(sorted(mr.FMT))
            + ' 중 하나여야 한다 : ' + kind)
        return

    f = arg('--find')
    if f:
        dofind(pid, kind, f)
        return

    n = arg('--next')
    if n:
        donext(pid, n)
        return

    if has('--cands'):
        docands(pid)
        return

    w = arg('--watch')
    if w:
        names = [x.strip() for x in w.split(',') if x.strip()]
        try:
            sec = float(arg('--sec', '1'))
        except ValueError:
            sec = 1.0
        watch(names, max(0.1, sec), pid)
        return

    if has('--objs'):
        try:
            limit = int(arg('--objs', '20'))
        except ValueError:
            limit = 20
        dumpobjs(limit, pid)
        return

    #--- 진단 ---
    modname = None
    name    = None

    if pid != None:
        hit  = [n for p, n in mr.procs() if p == pid]
        name = hit[0] if hit else '(알 수 없음)'
    else:
        #mem.json 의 process 로 찾는다
        m = mr.Mem(MEM_PATH, say)
        if not m.loadcfg():
            say(str(m.err))
            say()
            say('mem.json 이 아직 없거나 비었다. 먼저 클라이언트 PID 를 찾는다 :')
            say('  python memprobe.py --list')
            say('  python memprobe.py --pid <PID>')
            return
        want = str(m.cfg.get('process', '')).lower()
        modname = str(m.cfg.get('module', '')) or None
        hit = [(p, n) for p, n in mr.procs() if n.lower() == want]
        if len(hit) == 0:
            say("mem.json 의 process '" + want + "' 를 못 찾았다. 게임이 떠 있는지 확인하고,")
            say('이름이 다르면 --list 로 찾아 mem.json 의 process 를 고친다')
            say('  python memprobe.py --list')
            return
        if len(hit) > 1:
            say(str(len(hit)) + '개가 같은 이름으로 떠 있다 (듀얼클라) :')
            titles = mr.windows()
            for p, n in hit:
                t = titles.get(p, [])
                say('  PID %-8d %s' % (p, ' | '.join(t) if t else '(창 없음)'))
            say('진단은 첫 번째로 한다. 특정 창을 보려면 --pid <PID> 또는 --fg 를 쓴다')
            say()
        pid, name = hit[0]

    diag(pid, name, modname)


if __name__ == '__main__':
    #더블클릭으로 띄우면 메시지를 찍는 순간 콘솔이 같이 닫혀서 아무것도 읽을 수 없다.
    #예외가 나도 마찬가지다. 그래서 어떤 경우든 엔터를 기다리고 나서 끝낸다
    try:
        main()
    except KeyboardInterrupt:
        say()
        say('중단')
    except Exception:
        import traceback
        say()
        say('예기치 못한 오류 :')
        say(traceback.format_exc())
    finally:
        mr.holdconsole()
