#HP 주소를 한 번에 찾아 mem.json 까지 자동으로 채워주는 도구
#
#  쓰는 법 :   python hpfind.py
#
#  HP 숫자를 몰라도 된다. 게임 창에 들어가 있는 채로 키만 누르면 된다 :
#
#    1) 게임 창을 클릭한다
#    2) 몹한테 맞아서 HP 를 줄인다  ->  [1] 을 누른다
#    3) 또 맞는다                   ->  [1]
#    4) 또 맞는다                   ->  [1]
#    5) 끝. mem.json 이 저장되고, HP 가 맞게 읽히는지 바로 보여준다
#
#    중단하려면 [2]
#
#  키를 바꾸려면 :  python hpfind.py --key 1 --quit 2
#  (누른 키는 게임에도 같이 들어간다. 게임에서 1번이 스킬/아이템 슬롯이면
#   그것도 같이 눌리므로, 거슬리면 --key insert 처럼 안 쓰는 키로 바꾼다)
#
#  왜 이게 되는가 :
#    처음에 메모리를 통째로 기록해두고 두 가지 조건을 번갈아 건다 :
#      맞았을 때   -> '줄어든 자리' 만 남긴다
#      안 맞았을 때 -> '줄지 않은 자리' 만 남긴다
#
#    '줄어든 것' 만 거르면 안 된다. 게임 안에는 매초 알아서 줄어드는 타이머/카운터가
#    있어서, 그런 값은 모든 라운드를 통과해 HP 보다 더 잘 살아남는다. 실제로 그래서
#    엉뚱한 주소를 잡은 적이 있다. '맞지 않을 때는 줄지 않는다' 는 조건이 그걸 걸러낸다.
#    (HP 가 자연 회복해도 '줄지 않음' 에 해당하므로 같이 살아남는다)
#
#  읽기 전용이다. 게임 메모리에 아무것도 쓰지 않고, 게임에 키/마우스도 보내지 않는다.
#  고치는 파일은 mem.json 하나뿐이고, 고치기 전에 mem.json.bak 으로 백업한다.
#
#  Windows 전용.
import json
import os
import shutil
import sys
import time

import memread as mr
import memprobe as mp

#u32 와 u16 을 둘 다 본다. 구버전 클라이언트는 HP 가 2바이트인 경우가 흔하다.
#기록(스냅샷)은 원본 바이트라 타입과 무관하므로, 한 번 떠두고 양쪽으로 해석하면 된다
TYPES    = ['u32', 'u16']
ROUNDS   = 10       #최대 몇 단계까지 반복할지
ENOUGH   = 3        #후보가 이 수 이하로 줄면 그만한다
NEAR     = 128      #hp_max 를 찾을 때 hp 주변 몇 바이트를 볼지

#HP 로 말이 되는 범위. 이 밖의 값은 타이머나 포인터지 HP 가 아니다
HP_MIN   = 1
HP_MAX   = 1000000

#맞는 단계와 안 맞는 단계를 번갈아 한다
STEPS = [('몹한테 맞아서 HP 를 줄이세요',               'less',
          'HP 가 줄어든 것을 확인하고 누르세요'),
         ('이제 맞지 마세요 (도망치거나 안전한 곳으로)', 'notless',
          '맞지 않는 상태가 되면 누르세요')]
KEY_NEXT = '1'      #다음 단계. --key 로 바꿀 수 있다
KEY_QUIT = '2'      #중단.     --quit 로 바꿀 수 있다


def say(s=''):
    print(s)
    sys.stdout.flush()


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def line():
    say('=' * 66)


#키 이름이 쓸 수 있는 것인지 미리 본다.
#스냅샷을 다 뜬 뒤에 터지면 그 작업이 통째로 날아가므로 시작 전에 검사한다
def checkkeys():
    import keyboard as k
    for name, label in ((KEY_NEXT, '--key'), (KEY_QUIT, '--quit')):
        try:
            k.is_pressed(name)
        except Exception as e:
            say("키 이름 '" + str(name) + "' 를 쓸 수 없다 (" + label + ') : ' + str(e))
            say('  숫자는 1 2 3, 그 밖에 insert / end / home / f1 같은 이름을 쓴다')
            say('  (키패드 숫자가 아니라 글자 위 숫자열을 말한다)')
            return False
    if KEY_NEXT == KEY_QUIT:
        say('진행 키와 중단 키가 같다 : ' + str(KEY_NEXT))
        return False
    return True


#게임 창에 있는 채로 누를 수 있게 전역 키를 기다린다.
#돌려주는 것 : True(계속) / False(중단)
def waitkey(msg):
    import keyboard as k
    say(msg)
    say('   [%s] = 다음 단계   [%s] = 중단' % (KEY_NEXT.upper(), KEY_QUIT.upper()))
    #이전에 누른 게 남아 있으면 바로 지나가버린다. 떼는 것부터 기다린다
    while k.is_pressed(KEY_NEXT):
        time.sleep(0.05)
    while True:
        if k.is_pressed(KEY_QUIT):
            return False
        if k.is_pressed(KEY_NEXT):
            while k.is_pressed(KEY_NEXT):
                time.sleep(0.05)
            return True
        time.sleep(0.03)


#hp 주변에서 hp_max 로 보이는 자리를 찾는다.
#  - hp 와 같은 타입이고
#  - 지금 hp 보다 크거나 같고 (최대치니까)
#  - 상식 범위 안이고
#  - hp 와 가까울수록 좋다 (구조체 안에서 보통 바로 옆이다)
#돌려주는 것 : [(주소, 값, 간격), ...]  가까운 순
def findmax(m, addr, kind, hp):
    import struct
    fmt, size = mr.FMT[kind]
    lo  = addr - NEAR
    raw = mr.readmem(m.h, lo, NEAR * 2 + size)
    if raw == None:
        return []
    out = []
    for off in range(0, len(raw) - size + 1, size):
        a = lo + off
        if a == addr or a % size != 0:
            continue
        v = struct.unpack_from(fmt, raw, off)[0]
        if v < hp or v <= 0 or v > 1000000:
            continue
        out.append((a, v, a - addr))
    out.sort(key=lambda r: abs(r[2]))
    return out


#mem.json 의 chains 만 고쳐 쓴다. 나머지 키와 주석(_ 로 시작)은 건드리지 않는다
def writejson(path, base, hp, hpkind, hpmax, maxkind):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        say('mem.json 을 못 읽었다 : ' + str(e))
        return False

    if os.path.isfile(path):
        try:
            shutil.copyfile(path, path + '.bak')
            say('백업 : ' + path + '.bak')
        except Exception as e:
            say('백업 실패(계속 진행) : ' + str(e))

    ch = data.setdefault('chains', {})
    ch['hp'] = {'base': '0x%X' % (hp - base), 'offsets': [], 'type': hpkind}
    if hpmax != None:
        ch['hp_max'] = {'base': '0x%X' % (hpmax - base), 'offsets': [],
                        'type': maxkind}
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        say('mem.json 저장 실패 : ' + str(e))
        return False


#찾은 주소가 진짜 HP 인지 눈으로 확인시켜 준다.
#고른 것 하나만 보여주면 그게 틀렸을 때 알 길이 없으므로, 남은 후보를 전부 같이 찍는다
def verify(m, cands, chosen, seconds=15):
    import struct
    say()
    line()
    say('확인 : %d초간 후보들의 값을 읽어서 보여준다' % seconds)
    say('게임에서 맞거나 회복하면서, 어느 열이 HP 바와 같이 움직이는지 보세요')
    line()
    say()

    head = '  %-8s' % '시각'
    for i, (a, v, k) in enumerate(cands[:6], start=1):
        mark = '*' if a == chosen else ' '
        head += ' %s%d:0x%X(%s)' % (mark, i, a, k)
    say(head)
    say('  (* = mem.json 에 저장한 것)')
    say()

    end = time.time() + seconds
    while time.time() < end:
        row = '  %-8s' % time.strftime('%H:%M:%S')
        for a, v, k in cands[:6]:
            fmt, size = mr.FMT[k]
            raw = mr.readmem(m.h, a, size)
            cur = '--' if raw == None else struct.unpack(fmt, raw)[0]
            row += ' %14s' % cur
        say(row)
        time.sleep(1)


CANDS_FILE = 'hpfind_cands.json'


#지난번에 찾아둔 후보 중 n 번째로 mem.json 을 다시 쓴다.
#한 번 틀렸다고 처음부터 다시 맞으러 가는 건 낭비다
def repick(n):
    path = os.path.join(mr.appdir(), CANDS_FILE)
    if not os.path.isfile(path):
        say('이전 후보 기록이 없다 (' + path + ')')
        say('먼저 python hpfind.py 를 한 번 돌려야 한다')
        return
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        say('후보 기록을 못 읽었다 : ' + str(e))
        return

    cands = [(int(a), int(v), str(k)) for a, v, k in data.get('cands', [])]
    base  = int(data.get('base', 0))
    if not cands:
        say('후보 기록이 비어 있다')
        return
    if n < 1 or n > len(cands):
        say('%d번 후보는 없다. 1 ~ %d 중에서 고른다' % (n, len(cands)))
        for i, (a, v, k) in enumerate(cands, start=1):
            say('    %d : 0x%X (%s, 그때 값 %d)' % (i, a, k, v))
        return

    addr, v, kind = cands[n - 1]
    say('%d번 후보 0x%X (%s) 로 다시 저장한다' % (n, addr, kind))

    m = mr.Mem(mp.MEM_PATH, say)
    if not m.attach():
        say('붙기 실패 : ' + str(m.err))
        return
    try:
        if m.base != base:
            say('주의 : 모듈 베이스가 달라졌다 (0x%X -> 0x%X).' % (base, m.base))
            say('게임을 다시 켰다면 후보 주소가 안 맞을 수 있다. 처음부터 다시 하는 게 낫다')
        import struct
        fmt, size = mr.FMT[kind]
        raw = mr.readmem(m.h, addr, size)
        hp  = struct.unpack(fmt, raw)[0] if raw else None
        say('지금 그 주소의 값 : ' + str(hp))

        hpmax = None
        if hp != None:
            near = findmax(m, addr, kind, hp)
            if near:
                hpmax = near[0][0]
                say('hp_max 후보 : 0x%X (%d)' % (hpmax, near[0][1]))
        if not writejson(mp.MEM_PATH, m.base, addr, kind, hpmax, kind):
            return
        say('mem.json 저장 완료')
        verify(m, cands, addr)
    finally:
        m.detach()


def run():
    global KEY_NEXT, KEY_QUIT
    KEY_NEXT = arg('--key', KEY_NEXT)
    KEY_QUIT = arg('--quit', KEY_QUIT)

    line()
    say(' HP 주소 자동 찾기')
    line()
    say()
    say('진행 키 : [%s]    중단 키 : [%s]' % (KEY_NEXT.upper(), KEY_QUIT.upper()))
    say('  (게임 창에 있는 채로 눌러도 됩니다. 다른 키로 바꾸려면 --key / --quit)')
    say()
    if not checkkeys():
        return
    say('mem.json : ' + mp.MEM_PATH)
    if not mp.MEM_FOUND:
        say('mem.json 이 없다. 먼저 memprobe.py 와 같은 폴더에 두어야 한다')
        return
    say()

    #--- 붙기 : 쓸 게임 창을 맨 앞에 두게 한다 ---
    for i in (3, 2, 1):
        say('쓸 게임 창을 클릭해 맨 앞에 두세요... ' + str(i))
        time.sleep(1)
    pid = mr.frontpid()
    m   = mr.Mem(mp.MEM_PATH, say)
    if not m.attach(pid):
        #맨 앞 창이 게임이 아니면 이름으로 알아서 고르게 둔다
        m = mr.Mem(mp.MEM_PATH, say)
        if not m.attach():
            say('붙기 실패 : ' + str(m.err))
            return
    say()

    try:
        #--- 1. 지금 메모리를 통째로 기록 ---
        mp.SCAN_PATH = os.path.join(mr.appdir(), 'hpfind.dat')
        say('지금 메모리를 기록한다 (몇 초 걸린다)')
        t0 = time.time()
        n  = mp.savesnap(m, TYPES[0])
        if n == 0:
            return
        say('영역 %d개 기록 완료 (%.1f초)' % (n, time.time() - t0))
        say()

        groups = None
        for rnd in range(1, ROUNDS + 1):
            prompt, how, hint = STEPS[(rnd - 1) % len(STEPS)]
            line()
            say(' %d단계 : %s' % (rnd, prompt))
            line()
            if not waitkey('   ' + hint):
                say('중단')
                return
            say()

            if groups == None:
                #첫 단계만 기록 전체와 비교한다. 같은 기록을 타입별로 두 번 해석한다
                groups = []
                for kind in TYPES:
                    out = mp.snapnarrow(m, kind, how)
                    if out == None:
                        return
                    if len(out) > 0:
                        groups.append((kind, out))
            else:
                nxt = []
                for kind, cands in groups:
                    kept, table = mp.narrow(m, kind, cands, how)
                    if kept == None:
                        return
                    if len(kept) > 0:
                        nxt.append((kind, kept))
                groups = nxt

            total = sum(len(c) for k, c in groups)
            say('  %s -> 남은 후보 %d개  (%s)'
                % ('줄어든 자리만' if how == 'less' else '줄지 않은 자리만',
                   total,
                   ', '.join('%s %d' % (k, len(c)) for k, c in groups)
                   if groups else '없음'))
            say()

            if total == 0:
                line()
                say('후보가 하나도 안 남았다')
                line()
                say()
                if how == 'less':
                    say('HP 가 실제로 줄기 전에 키를 눌렀을 가능성이 크다.')
                    say('HP 바가 눈에 띄게 줄어든 것을 확인한 뒤 누르세요.')
                else:
                    say('안 맞는 단계인데 HP 가 줄었을 가능성이 크다.')
                    say('독이나 지속 피해가 없는 안전한 곳에서 다시 해보세요.')
                say('다시 하려면 : python hpfind.py')
                return

            #두 조건을 모두 한 번씩은 겪은 뒤에 멈춰야 의미가 있다
            if total <= ENOUGH and rnd >= len(STEPS):
                say('  충분히 좁혀졌다')
                break
            if rnd == ROUNDS:
                say('  %d단계를 했는데도 후보가 %d개 남았다' % (rnd, total))
                if total > 10:
                    say()
                    say('후보가 너무 많아 여기서 멈춘다. 다시 : python hpfind.py')
                    return

        #--- 2. 결과 ---
        cands = [(a, v, k) for k, cs in groups for a, v in cs]
        cands.sort()

        #HP 로 말이 안 되는 값은 뒤로 보낸다.
        #6억 같은 값은 타이머나 포인터지 HP 가 아니다 (실제로 그걸 잡은 적이 있다)
        def sane(v):
            return HP_MIN <= v <= HP_MAX

        good = [c for c in cands if sane(c[1])]
        bad  = [c for c in cands if not sane(c[1])]

        line()
        say(' 찾은 후보 %d개' % len(cands))
        line()
        say()
        say('  %-18s %-6s %-12s %s' % ('주소', '타입', '현재 값', '판단'))
        for a, v, k in cands[:10]:
            note = '' if sane(v) else '<- HP 로는 말이 안 되는 값'
            say('  0x%-16X %-6s %-12d %s' % (a, k, v, note))
        say()

        if len(good) == 0:
            say('HP 로 쓸 만한 값이 하나도 없다. 전부 타이머나 포인터로 보인다.')
            say('다시 하려면 : python hpfind.py')
            return

        #같은 바이트를 겹쳐 읽는 후보가 섞일 수 있다 (u32 와 그 위쪽 절반 u16 등)
        for a, v, k in good:
            for a2, v2, k2 in good:
                if a2 > a and a2 < a + mr.FMT[k][1]:
                    say('참고 : 0x%X(%s) 와 0x%X(%s) 는 같은 바이트를 겹쳐 읽는다'
                        % (a, k, a2, k2))
                    break

        addr, hp, kind = good[0]
        if len(good) > 1:
            say('후보가 %d개 남았다. 0x%X (%s, 현재 %d) 로 저장하고,'
                % (len(good), addr, kind, hp))
            say('아래 확인에서 남은 후보를 전부 같이 보여준다.')
            say('다른 쪽이 HP 와 맞으면 그 주소로 다시 저장하면 된다 :')
            say('    python hpfind.py --pick 2        (2번째 후보로)')
            say()

        #--pick 으로 다시 고를 수 있게 후보를 남겨둔다
        try:
            with open(os.path.join(mr.appdir(), CANDS_FILE),
                      'w', encoding='utf-8') as f:
                json.dump({'base': m.base,
                           'cands': [[a, v, k] for a, v, k in good]}, f)
        except Exception:
            pass

        #--- 3. hp_max 찾기 ---
        near = findmax(m, addr, kind, hp)
        hpmax = None
        if near:
            say('HP 주변에서 최대치로 보이는 값 :')
            for a, v, d in near[:6]:
                say('    0x%-16X %-8d (hp 에서 %+d 바이트)' % (a, v, d))
            hpmax = near[0][0]
            say()
            say('가장 가까운 0x%X (%d) 를 hp_max 로 쓴다' % (hpmax, near[0][1]))
        else:
            say('주변에서 hp_max 로 쓸 값을 못 찾았다. hp 만 저장한다')
        say()

        #--- 4. mem.json 쓰기 ---
        if not writejson(mp.MEM_PATH, m.base, addr, kind, hpmax, kind):
            return
        say('mem.json 저장 완료')
        say('    "hp":     { "base": "0x%X", "offsets": [], "type": "%s" }'
            % (addr - m.base, kind))
        if hpmax != None:
            say('    "hp_max": { "base": "0x%X", "offsets": [], "type": "%s" }'
                % (hpmax - m.base, kind))

        #--- 5. 바로 확인 ---
        verify(m, good, addr)

        say()
        line()
        say(' 끝났다')
        line()
        say()
        say('* 표시한 열이 HP 바와 같이 움직였으면 성공이다.')
        say('다른 열이 HP 와 맞았으면 그 번호로 다시 저장한다 :')
        say('    python hpfind.py --pick 2')
        say('어느 것도 안 맞으면 처음부터 다시 : python hpfind.py')
        say()
        say('다음 단계는 pit.py 에서 [메모리에서 상태 읽기] 를 켜는 것이다.')
        say('(혈맹 판별과 몹 타겟은 objlist 가 필요한데, HP 귀환만 쓸 거면 안 해도 된다)')
    finally:
        m.detach()
        try:
            os.unlink(os.path.join(mr.appdir(), 'hpfind.dat'))
        except Exception:
            pass


if __name__ == '__main__':
    try:
        if not mr.IS_WIN:
            say('이 도구는 Windows 에서만 된다 (지금 : ' + sys.platform + ')')
        else:
            pick = arg('--pick')
            if pick != None:
                try:
                    repick(int(pick))
                except ValueError:
                    say('--pick 은 숫자여야 한다 : ' + str(pick))
            else:
                run()
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
