#manapot.py - MP 가 떨어지면 "농축마력의물약" 을 바로 사용하는 단일 목적 스크립트
#
#  하는 일 :
#    1. 게임 메모리에서 MP 를 읽는다 (읽기 전용. memread.py 의 보안 홀더 디코드를 그대로 쓴다)
#    2. MP 비율이 기준(기본 60%) 이하로 내려가면, 소지품에서 농축마력의물약을 찾아
#       그 아이템을 바로 사용한다 (itemcast.py — 게임 함수 FUN_0045a380 직접 호출).
#    3. 쿨타임(기본 3초) 동안은 다시 쓰지 않는다 (물약 연타 방지)
#
#  단축키 칸(F5~F12)을 거치지 않고, 소지품에 있는 아이템을 id 로 바로 쓴다.
#  마우스/키보드 입력을 전혀 보내지 않는다. 메모리에는 아무것도 쓰지 않는다 (사용 함수 호출만 한다).
#
#  주의 (CLAUDE.md 규칙 3):
#    아이템 직접 사용은 코드 주입(메인 스레드 APC)으로 동작한다 — 감지/밴 리스크가 있는
#    방법 2 다 (2026-10-27 밴 전력). skillcast.py 와 같은 선 위에 있다.
#    자기 자신에게 쓰는 평범한 아이템(물약 등)만 된다. 대상 선택이 필요한 아이템은 안 된다.
#
#  쓰는 법 (Windows, 게임을 띄운 상태에서, 게임과 같은 관리자 권한으로) :
#
#     python manapot.py                   MP 60% 이하면 농축마력의물약 사용, 0.5초마다 확인
#     python manapot.py --pct 50          기준 MP 비율을 50% 로
#     python manapot.py --name 마력회복물약  찾을 아이템 이름을 바꾼다
#     python manapot.py --id 268435601    이름 대신 아이템 객체 id 를 직접 지정
#     python manapot.py --gap 2           같은 물약을 다시 쓰기까지 최소 간격(초)
#     python manapot.py --sec 1           MP 를 확인하는 주기(초)
#     python manapot.py --pid 1234        PID 직접 지정 (python memprobe.py --list 로 확인)
#     python manapot.py --dry             실제로 안 쓰고 '썼을 것' 만 로그로 본다
#     python manapot.py --items           소지품에서 이름이 맞는 아이템만 찍고 끝낸다
#
#  멈추기 : Tab 키(keyboard 모듈이 있으면) 또는 Ctrl+C.
#
#  같은 폴더에 memread.py / itemcast.py / mem.json 이 있어야 한다.

import os
import sys
import time

import memread as mr
import itemcast as ic

POTION_NAME = '농축마력의물약'   #기본으로 찾을 아이템 이름
MP_PCT      = 60.0              #이 비율 이하면 쓴다
POLL_SEC    = 0.5              #MP 확인 주기(초)
PRESS_GAP   = 3.0              #같은 물약 재사용 최소 간격(초)


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def has(name):
    return name in sys.argv


def pickpid():
    raw = arg('--pid')
    if raw != None:
        try:
            return int(raw)
        except ValueError:
            print('--pid 는 숫자여야 한다 : ' + str(raw))
            sys.exit(1)
    #--pid 가 없으면 맨 앞 창에 붙게 둔다 (attach 가 알아서 고른다). 3초 준다
    print('쓸 게임 창을 맨 앞에 둬라. 3초 뒤 맨 앞 창에 붙는다...')
    time.sleep(3)
    return None


#이름을 비교하기 좋게 다듬는다 (공백 제거)
def _norm(s):
    return ''.join((s or '').split())


#소지품에서 이름이 target 을 포함하는 아이템을 찾는다. (아이템 dict or None, 사유).
#수량이 있는 칸을 먼저 고른다. 못 읽으면 win 이 None.
def finditem(mem, target):
    try:
        items, win, _ = mem.item_table()
    except Exception as e:
        return None, '소지품을 못 읽었다 : %s' % e
    if win == None:
        return None, '소지품 창을 못 읽었다 (캐릭터로 월드에 들어간 뒤 다시)'
    want = _norm(target)
    match = []
    for it in items:
        if it.get('name') and want != '' and want in _norm(it['name']):
            match.append(it)
    if len(match) == 0:
        return None, "소지품에 '%s' 이(가) 없다" % target
    #수량이 1 이상인 칸을 먼저, 없으면 첫 칸
    for it in match:
        if (it.get('count') or 0) > 0:
            return it, None
    return match[0], None


def main():
    mempath = os.path.join(mr.appdir(), 'mem.json')
    target  = arg('--name', POTION_NAME)
    forceid = arg('--id')           #이름 대신 아이템 객체 id 직접 지정
    dry     = has('--dry')
    try:
        pct = float(arg('--pct', str(MP_PCT)))
    except ValueError:
        pct = MP_PCT
    try:
        gap = float(arg('--gap', str(PRESS_GAP)))
    except ValueError:
        gap = PRESS_GAP
    try:
        sec = max(0.1, float(arg('--sec', str(POLL_SEC))))
    except ValueError:
        sec = POLL_SEC

    fixed_id = None
    if forceid != None:
        try:
            fixed_id = int(forceid)
        except ValueError:
            print('--id 는 숫자여야 한다 : ' + str(forceid))
            sys.exit(1)

    mem = mr.Mem(mempath, print)
    pid = pickpid()
    if not mem.attach(pid):
        print('붙기 실패 : ' + str(mem.err))
        return

    try:
        #--items : 이름이 맞는 소지품만 보여주고 끝낸다
        if has('--items'):
            items, win, cnt = mem.item_table()
            if win == None:
                print('소지품 창을 못 읽었다 (캐릭터로 월드에 들어간 뒤 다시)')
                return
            want = _norm(target)
            print("=== 소지품에서 '%s' 찾기 (창 아이템 %s개) ===" % (target, str(cnt)))
            found = False
            for it in items:
                if it.get('name') and want != '' and want in _norm(it['name']):
                    found = True
                    print('  id %-12d 수량 %-6s 종류 %-3s  %s'
                          % (it['id'], str(it.get('count')), str(it.get('use')), it['name']))
            if not found:
                print('  (없음)')
            return

        print('=== 농축마력의물약 바로 사용  -  메모리 읽기 + 함수 직접 호출(방법 2) ===')
        print('찾는 이름 : %s   기준 : MP %.0f%% 이하   재사용 간격 : %.1f초   확인 주기 : %.1f초%s'
              % (target, pct, gap, sec, '   [연습 모드]' if dry else ''))
        if fixed_id != None:
            print('아이템 id 고정 : %d (이름 검색 안 함)' % fixed_id)

        caster = ic.ItemCaster(mem.pid, mem.base)
        if caster.h is None and not dry:
            print('아이템 사용 준비 실패 : ' + str(caster.err))
            caster.close()
            return

        #Tab 비상 정지 (keyboard 모듈이 있을 때만). 이 프로그램 제어라 규칙에 어긋나지 않는다
        stop = {'v': False}
        try:
            import keyboard
            keyboard.add_hotkey('tab', lambda: stop.update(v=True))
            print('멈추려면 Tab 또는 Ctrl+C')
        except Exception:
            print('멈추려면 Ctrl+C (keyboard 모듈이 없어 Tab 정지는 못 건다)')

        last_use  = 0.0
        warned_mp = False     #MP 못 읽음 경고를 한 번만 찍는다
        warned_it = False     #아이템 못 찾음 경고를 한 번만 찍는다

        try:
            while not stop['v']:
                t0 = time.time()
                mppct = mem.mppct()
                if mppct == None:
                    if not warned_mp:
                        print('MP 를 못 읽어서 건너뛴다 (mem.json 의 mp/mp_max, secure.mp 확인)')
                        warned_mp = True
                    time.sleep(sec)
                    continue
                warned_mp = False

                if mppct <= pct:
                    now = time.time()
                    if now - last_use < gap:
                        time.sleep(max(0.0, sec - (time.time() - t0)))
                        continue

                    #쓸 아이템 id 를 정한다 : 고정 id > 이름으로 소지품 검색
                    if fixed_id != None:
                        item_id, label = fixed_id, '%s(id %d)' % (target, fixed_id)
                    else:
                        it, why = finditem(mem, target)
                        if it == None:
                            if not warned_it:
                                print(why)
                                warned_it = True
                            time.sleep(sec)
                            continue
                        warned_it = False
                        item_id = it['id']
                        label = '%s(id %d, 수량 %s)' % (it['name'], item_id, str(it.get('count')))

                    print('MP %.0f%% <= %.0f%% -> %s 사용' % (mppct, pct, label))
                    if dry:
                        print('  [연습] 아이템 id %d 를 사용했을 것' % item_id)
                        last_use = now
                    else:
                        ok = caster.use(item_id)
                        if ok:
                            print('  사용 패킷 보냄')
                            last_use = now
                        else:
                            print('  사용 실패 : ' + str(caster.err))
                            #실패해도 바로 다시 때리지 않게 쿨타임만큼 쉰다
                            last_use = now
                time.sleep(max(0.0, sec - (time.time() - t0)))
        except KeyboardInterrupt:
            pass
        finally:
            caster.close()
    finally:
        mem.detach()
        print('멈춤')


if __name__ == '__main__':
    main()
