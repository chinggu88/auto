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
#   python memprobe.py --find 1234,2500 --fg   HP 1234, HP최대 2500 일 때
#                                              둘이 붙어 있는 자리를 한 번에 찾는다
#   python memprobe.py --find 1234 --fg        값 하나로 찾기
#   python memprobe.py --next 1100 --fg        맞아서 HP 가 1100 이 됐을 때 좁히기
#   python memprobe.py --next less --fg        값은 모르지만 줄었을 때
#   python memprobe.py --next more --fg        회복해서 늘었을 때
#   python memprobe.py --next same --fg        안 변했을 때
#   python memprobe.py --cands                 지금 남은 후보 보기
#   python memprobe.py --find 123 --type u16   2바이트 값으로 찾기 (기본은 u32)
#
#   후보는 scan.dat 에 저장된다. 처음부터 다시 하려면 그 파일을 지운다.
#   HP 와 HP최대를 같이 아는 경우 --find <hp>,<hpmax> 가 압도적으로 빠르다
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

MEM_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'mem.json')


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

SCAN_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'scan.dat')
SCAN_MAGIC = b'MSCAN2\n'


#후보 저장 : [(주소, 값), ...]
def savecands(kind, cands):
    import struct
    with open(SCAN_PATH, 'wb') as f:
        f.write(SCAN_MAGIC)
        k = kind.encode('ascii')
        f.write(struct.pack('<B', len(k)) + k)
        f.write(struct.pack('<Q', len(cands)))
        for a, v in cands:
            f.write(struct.pack('<Qq', a, v))


def loadcands():
    import struct
    if not os.path.isfile(SCAN_PATH):
        return None, []
    try:
        with open(SCAN_PATH, 'rb') as f:
            if f.read(len(SCAN_MAGIC)) != SCAN_MAGIC:
                return None, []
            n    = struct.unpack('<B', f.read(1))[0]
            kind = f.read(n).decode('ascii')
            cnt  = struct.unpack('<Q', f.read(8))[0]
            out  = []
            for _ in range(cnt):
                out.append(struct.unpack('<Qq', f.read(16)))
        return kind, out
    except Exception as e:
        say('scan.dat 읽기 실패 : ' + str(e))
        return None, []


#'u32' -> (struct 포맷, 바이트수, 정렬)
def kindinfo(kind):
    fmt, size = mr.FMT[kind]
    return fmt, size, size


#지금 메모리에서 kind 타입으로 value 와 같은 자리를 전부 찾는다
#pair 가 있으면 'value 바로 뒤 win 바이트 안에 pair 도 있는' 자리만 남긴다
def scanall(m, kind, value, pair=None, win=64):
    import struct
    fmt, size, align = kindinfo(kind)
    try:
        needle = struct.pack(fmt, value)
    except struct.error:
        say('%s 타입에 안 들어가는 값이다 : %d' % (kind, value))
        return None

    pneedle = None
    if pair != None:
        try:
            pneedle = struct.pack(fmt, pair)
        except struct.error:
            say('%s 타입에 안 들어가는 값이다 : %d' % (kind, pair))
            return None

    regs  = mr.regions(m.h, writable=True,
                       maxaddr=(1 << 32) if m.ptrsz == 4 else None)
    total = sum(r[1] for r in regs)
    say('검색 영역 %d개, %.1f MB' % (len(regs), total / 1048576.0))

    cands = []
    done  = 0
    for base, size_r in regs:
        for at, raw in mr.readchunks(m.h, base, size_r):
            pos = raw.find(needle)
            while pos >= 0:
                addr = at + pos
                if addr % align == 0:
                    if pneedle == None:
                        cands.append((addr, value))
                    else:
                        #짝이 가까이 있는지 본다 (hp 와 hp최대는 보통 붙어 있다)
                        tail = raw[pos + size: pos + size + win]
                        q = tail.find(pneedle)
                        if q >= 0 and (addr + size + q) % align == 0:
                            cands.append((addr, value))
                pos = raw.find(needle, pos + 1)
                if len(cands) > 2000000:
                    say('후보가 너무 많다(200만 초과). 더 특이한 값으로 다시 찾는다')
                    return None
        done += size_r
    return cands


#이미 있는 후보만 다시 읽어 좁힌다. how : 숫자 / less / more / same / changed
def narrow(m, kind, cands, how):
    import struct
    fmt, size, align = kindinfo(kind)
    want = None
    if how not in ('less', 'more', 'same', 'changed'):
        try:
            want = int(how, 0)
        except ValueError:
            say("--next 는 숫자 또는 less / more / same / changed 다 : " + how)
            return None

    out = []
    for addr, old in cands:
        raw = mr.readmem(m.h, addr, size)
        if raw == None:
            continue
        cur = struct.unpack(fmt, raw)[0]
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
    return out


#후보를 보여준다. 적어지면 mem.json 에 그대로 붙여 넣을 줄까지 만들어 준다
def showcands(m, kind, cands, limit=30):
    say()
    say('남은 후보 : ' + str(len(cands)) + '개')
    if len(cands) == 0:
        say('  너무 많이 좁혔다. scan.dat 를 지우고 --find 부터 다시 한다')
        return
    if len(cands) > limit:
        say('  (앞 %d개만 표시. 게임에서 값을 바꾸고 --next 로 더 좁힌다)' % limit)
    say()
    say('  %-18s %-12s %s' % ('절대주소', '값', 'mem.json 에 넣을 base (상대값)'))
    for addr, val in cands[:limit]:
        rva = addr - m.base
        mark = '0x%X' % rva if 0 <= rva < (1 << 32) else '(모듈 밖 - 포인터 필요)'
        say('  0x%-16X %-12d %s' % (addr, val, mark))
    say()
    if len(cands) <= limit:
        say('후보가 몇 개 안 남았으면, 게임에서 HP 를 바꾸고 --next <새값> 으로 한 번 더')
        say('확인한 뒤 살아남은 주소를 쓴다. 그 다음 mem.json 의 chains 에 이렇게 적는다 :')
        a, v = cands[0]
        say('')
        say('    "hp": { "base": "0x%X", "offsets": [], "type": "%s" },'
            % (a - m.base, kind))
        say('')
        say('그리고 python memprobe.py --watch hp 로 값이 따라 움직이는지 본다')


def dofind(pid, kind, spec):
    m = mr.Mem(MEM_PATH, say)
    if not m.attach(pid):
        say('붙기 실패 : ' + str(m.err))
        return
    try:
        pair = None
        if ',' in spec:
            a, b = spec.split(',', 1)
            value, pair = int(a.strip(), 0), int(b.strip(), 0)
            say('값 %d 바로 뒤에 %d 가 붙어 있는 자리를 찾는다 (%s)'
                % (value, pair, kind))
            say('  HP 와 HP최대는 보통 구조체 안에서 붙어 있어서, 둘을 같이 주면')
            say('  한 번에 후보가 몇 개로 줄어든다')
        else:
            value = int(spec.strip(), 0)
            say('값 %d 를 찾는다 (%s)' % (value, kind))
        say()

        t0 = time.time()
        cands = scanall(m, kind, value, pair)
        if cands == None:
            return
        say('걸린 시간 %.1f초' % (time.time() - t0))
        savecands(kind, cands)
        showcands(m, kind, cands)
        if len(cands) > 30:
            say('게임에서 HP 를 바꾼 뒤 :  python memprobe.py --next <새 HP 값> --fg')
    finally:
        m.detach()


def donext(pid, how):
    kind, cands = loadcands()
    if kind == None or len(cands) == 0:
        say('이전 검색 결과(scan.dat)가 없다. 먼저 --find 로 찾는다')
        return
    m = mr.Mem(MEM_PATH, say)
    if not m.attach(pid):
        say('붙기 실패 : ' + str(m.err))
        return
    try:
        say('이전 후보 ' + str(len(cands)) + '개를 ' + how + ' 로 좁힌다 (' + kind + ')')
        out = narrow(m, kind, cands, how)
        if out == None:
            return
        savecands(kind, out)
        showcands(m, kind, out)
    finally:
        m.detach()


def docands(pid):
    kind, cands = loadcands()
    if kind == None:
        say('scan.dat 가 없다. 먼저 --find 로 찾는다')
        return
    m = mr.Mem(MEM_PATH, say)
    if not m.attach(pid):
        say('붙기 실패 : ' + str(m.err))
        return
    try:
        showcands(m, kind, cands)
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
    if not mr.IS_WIN:
        say('이 도구는 Windows 에서만 된다 (지금 : ' + sys.platform + ')')
        say('게임이 도는 윈도우 PC 에서 돌려야 한다')
        return

    if has('--list'):
        dolist(arg('--list'))
        return

    pid = pickpid()
    if pid == -1:            #--pid / --fg 가 잘못됐다
        return

    kind = arg('--type', 'u32')
    if kind not in mr.FMT:
        say('--type 은 ' + ', '.join(sorted(mr.FMT)) + ' 중 하나여야 한다 : ' + kind)
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
