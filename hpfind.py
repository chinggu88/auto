#HP 주소를 한 번에 찾아 mem.json 까지 자동으로 채워주는 도구
#
#  쓰는 법 :   python hpfind.py
#
#  HP 숫자를 몰라도 된다. 게임 창에 들어가 있는 채로 키만 누르면 된다 :
#
#    1) 게임 창을 클릭한다
#    2) 몹한테 맞아서 HP 를 줄인다  ->  [insert] 를 누른다
#    3) 또 맞는다                   ->  [insert]
#    4) 또 맞는다                   ->  [insert]
#    5) 끝. mem.json 이 저장되고, HP 가 맞게 읽히는지 바로 보여준다
#
#  왜 이게 되는가 :
#    처음에 메모리를 통째로 기록해두고, 맞을 때마다 "직전보다 줄어든 자리" 만 남긴다.
#    HP 는 맞을 때마다 반드시 줄어들지만, 다른 값들이 세 번 연속 줄어들 일은 거의 없다.
#    그래서 서너 번이면 후보가 몇 개로 줄어든다.
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
ROUNDS   = 8        #최대 몇 번까지 반복할지. 보통 3번이면 몇 개로 줄어든다
ENOUGH   = 3        #후보가 이 수 이하로 줄면 그만한다
NEAR     = 128      #hp_max 를 찾을 때 hp 주변 몇 바이트를 볼지
KEY_NEXT = 'insert'
KEY_QUIT = 'end'


def say(s=''):
    print(s)
    sys.stdout.flush()


def line():
    say('=' * 66)


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


#찾은 주소가 진짜 HP 인지 눈으로 확인시켜 준다
def verify(m, seconds=12):
    say()
    line()
    say('확인 : 지금부터 %d초간 HP 를 읽어서 보여준다' % seconds)
    say('게임에서 맞거나 회복하면서 숫자가 따라 움직이는지 보세요')
    line()
    say()
    end = time.time() + seconds
    while time.time() < end:
        hp  = m.value('hp')
        mx  = m.value('hp_max')
        pct = m.hppct()
        say('  %s   hp = %-8s hp_max = %-8s %s'
            % (time.strftime('%H:%M:%S'),
               '--' if hp == None else hp,
               '--' if mx == None else mx,
               '' if pct == None else '(%.1f%%)' % pct))
        time.sleep(1)


def run():
    line()
    say(' HP 주소 자동 찾기')
    line()
    say()
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
            line()
            say(' %d번째 : 몹한테 맞아서 HP 를 줄이세요' % rnd)
            line()
            if not waitkey('   HP 가 줄었으면 키를 누르세요.'):
                say('중단')
                return
            say()

            if groups == None:
                #첫 번째만 기록 전체와 비교한다. 같은 기록을 타입별로 두 번 해석한다
                groups = []
                for kind in TYPES:
                    out = mp.snapnarrow(m, kind, 'less')
                    if out == None:
                        return
                    if len(out) > 0:
                        groups.append((kind, out))
            else:
                nxt = []
                for kind, cands in groups:
                    kept, table = mp.narrow(m, kind, cands, 'less')
                    if kept == None:
                        return
                    if len(kept) > 0:
                        nxt.append((kind, kept))
                groups = nxt

            total = sum(len(c) for k, c in groups)
            say('  남은 후보 : %d개  (%s)'
                % (total, ', '.join('%s %d' % (k, len(c)) for k, c in groups)
                   if groups else '없음'))
            say()

            if total == 0:   #과하게 좁혀졌다
                line()
                say('후보가 하나도 안 남았다')
                line()
                say()
                say('HP 가 실제로 줄기 전에 키를 눌렀을 가능성이 크다.')
                say('맞아서 HP 바가 눈에 띄게 줄어든 것을 확인한 다음 키를 누르세요.')
                say('다시 하려면 : python hpfind.py')
                return
            if total <= ENOUGH and rnd >= 2:
                say('  충분히 좁혀졌다')
                break
            if rnd == ROUNDS:
                #끝까지 많이 남았는데 첫 번째를 덥석 쓰면 엉뚱한 주소를 넣게 된다
                say('  %d번을 했는데도 후보가 %d개 남았다' % (rnd, total))
                say('  HP 가 확실히 줄어든 뒤에 키를 눌렀는지 확인하고 다시 돌려본다')
                if total > 10:
                    say()
                    say('후보가 너무 많아 여기서 멈춘다. 다시 : python hpfind.py')
                    return

        #--- 2. 결과 ---
        cands = [(a, v, k) for k, cs in groups for a, v in cs]
        cands.sort()
        line()
        say(' 찾은 후보 %d개' % len(cands))
        line()
        say()
        say('  %-18s %-6s %-10s %s' % ('주소', '타입', '현재 HP', 'mem.json base'))
        for a, v, k in cands[:10]:
            say('  0x%-16X %-6s %-10d 0x%X' % (a, k, v, a - m.base))
        say()

        addr, hp, kind = cands[0]
        if len(cands) > 1:
            say('후보가 여럿이라 첫 번째(0x%X)로 진행한다.' % addr)
            say('아래 확인에서 숫자가 안 맞으면 다시 돌리면 된다.')
            say()

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
        m.cfg = None
        if not m.loadcfg():
            say('저장한 mem.json 을 다시 못 읽었다 : ' + str(m.err))
            return
        verify(m)

        say()
        line()
        say(' 끝났다')
        line()
        say()
        say('위에서 hp 가 맞을 때 줄고 회복할 때 늘었으면 성공이다.')
        say('숫자가 이상하면 다시 돌리면 된다 : python hpfind.py')
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
