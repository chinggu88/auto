#메모리 읽기가 가능한지 먼저 가리는 도구 (Phase 0 게이트) + 값 확인용 감시기
#
#  읽기 전용이다. 게임에 키/마우스 입력을 전혀 보내지 않고, 메모리도 쓰지 않는다
#
#쓰는 법 (Windows, 게임을 띄운 상태에서) :
#
#   python memprobe.py --list            돌고 있는 프로세스 전부
#   python memprobe.py --list lin        이름에 'lin' 이 든 것만
#   python memprobe.py --pid 1234        그 PID 로 진단 (mem.json 없어도 된다)
#   python memprobe.py                   mem.json 의 process 로 진단
#
#   python memprobe.py --watch hp,mp              값이 실제로 따라 움직이는지 확인
#   python memprobe.py --watch hp,mp --sec 0.5    감시 주기 바꾸기
#   python memprobe.py --objs                     객체 목록 덤프
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
    rows.sort(key=lambda r: r[1].lower())

    say('프로세스 ' + str(len(rows)) + '개' + (" (필터 '" + filt + "')" if filt else ''))
    say()
    for pid, name in rows:
        say('  %-8d %s' % (pid, name))
    say()
    say("클라이언트를 찾았으면 : python memprobe.py --pid <PID>")


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
        say('다음에 할 일 :')
        say('  1. CheatEngine 등으로 HP / HP최대 주소를 찾는다')
        say('  2. 찾은 값을 ' + mname + ' 베이스(0x%X) 기준 상대값으로 바꾼다' % base)
        say('       상대값 = 절대주소 - 0x%X' % base)
        say('  3. mem.json 의 chains.hp.base 에 그 상대값을 넣는다')
        say('  4. python memprobe.py --watch hp,hp_max 로 값이 따라 움직이는지 확인한다')
        say()
        say('     ! 게임을 재시작하면 베이스 주소가 바뀐다(ASLR). 그래서 절대주소가 아니라')
        say('       모듈 기준 상대값으로 적어야 매번 다시 안 찾아도 된다')
        return True
    finally:
        mr.closeproc(h)


#=====================================================================
# 값 감시
#=====================================================================

def watch(names, sec):
    m = mr.Mem(MEM_PATH, say)
    if not m.attach():
        say('붙기 실패 : ' + str(m.err))
        return

    say()
    say('감시 : ' + ', '.join(names) + '   (' + str(sec) + '초 주기, ctrl+c 로 중단)')
    say('게임에서 맞거나 회복하거나 움직이면서 숫자가 따라 움직이는지 본다')
    say()

    #체인에 없는 이름을 적었으면 미리 알려준다
    known = list((m.cfg.get('chains') or {}).keys())
    for n in names:
        if n not in known and n not in ('hp%', 'mp%', 'pos'):
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

def dumpobjs(limit):
    m = mr.Mem(MEM_PATH, say)
    if not m.attach():
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

    w = arg('--watch')
    if w:
        names = [x.strip() for x in w.split(',') if x.strip()]
        try:
            sec = float(arg('--sec', '1'))
        except ValueError:
            sec = 1.0
        watch(names, max(0.1, sec))
        return

    if has('--objs'):
        try:
            limit = int(arg('--objs', '20'))
        except ValueError:
            limit = 20
        dumpobjs(limit)
        return

    #--- 진단 ---
    pid     = arg('--pid')
    modname = None
    name    = None

    if pid != None:
        try:
            pid = int(pid)
        except ValueError:
            say('--pid 는 숫자여야 한다 : ' + str(pid))
            return
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
            return
        pid, name = hit[0]

    diag(pid, name, modname)


if __name__ == '__main__':
    main()
