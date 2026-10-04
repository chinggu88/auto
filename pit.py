#핏빛서버 전용 사냥 매크로 : 상태를 화면 이미지가 아니라 프로세스 메모리에서 읽는다
#
#  main.py 는 한 줄도 고치지 않는다. 지금 돌아가는 매크로이므로 그대로 두고,
#  이 파일이 main 을 import 해서 바뀌는 부분만 다시 쓴다
#
#  main.py 에서 그대로 가져다 쓰는 것 :
#    로그/타이머/PENDING 큐, 마우스 이동, 커서 캘리브레이션, 버프/변신/귀환 동작,
#    소리 감지(FightGate), 이미지 폴백(마크 템플릿), 설정 저장/불러오기, GUI 틀
#
#  이 파일이 새로 쓰는 것 :
#    _checkrHp  - 피/마크 감시를 HP 숫자 + 혈맹명 비교로
#    huntloop   - 커서 스윕 대신 몹 목록에서 좌표를 집어 바로 찍는다
#
#  설계 원칙
#    1. 오프셋은 코드가 아니라 mem.json 에 둔다. 패치마다 json 만 고친다
#    2. 커서 확인은 절대 안 뺀다. 메모리에서 좌표를 얻어도 클릭 전에 main._probe()
#       를 통과시킨다. 오프셋이 밀려 엉뚱한 좌표가 나와도 커서가 아니라고 하면
#       클릭하지 않는다 -> 실패해도 '아무 일도 안 함' 으로 끝난다
#    3. 메모리는 가속기, 이미지는 폴백. 메모리가 죽으면 main.py 동작으로 떨어진다
#    4. 읽기 전용. memread.py 에 쓰기 함수가 없다
#
#  Windows 전용. 메모리 감지를 끄면 main.py 와 완전히 같게 돈다
import json
import os
import threading
import time
import traceback

import main
import memread as mr

log = main.log

PIT_PATH = os.path.join(main.APP_DIR, 'pit.json')
MEM_PATH = os.path.join(main.APP_DIR, 'mem.json')

#=====================================================================
# 설정
#=====================================================================

DEFAULT_PIT = {'mem':    False,   #메모리 감지 사용. 끄면 100% main.py 동작
               'hp_pct': 40,      #이 % 아래면 귀환
               'mp_pct': 0,       #이 % 아래면 귀환. 0 이면 MP 감시 끔
               'clans':  [],      #내 혈맹명. 여기 없는 혈맹이 보이면 적대로 본다
               'target': True}    #몹 목록으로 타겟 집기. 끄면 HP/혈맹만 메모리, 스윕 유지

MEM_ON    = DEFAULT_PIT['mem']
HP_PCT    = DEFAULT_PIT['hp_pct']
MP_PCT    = DEFAULT_PIT['mp_pct']
CLANS     = []
TARGET_ON = DEFAULT_PIT['target']

MEM = None          #memread.Mem 인스턴스

SCREEN     = None   #화면 크기 캐시
MEM_TRY    = 5      #한 번에 시도할 몹 수 (가까운 순)
MISS_LIMIT = 8      #타겟 좌표가 이만큼 연속으로 빗나가면 스윕으로 강등
COOL_SEC   = 3.0    #찍었는데 커서가 아니었던 몹을 이 시간만큼 건너뛴다
NOMOB_SEC  = 2.0    #'몹 없음' 을 이 간격으로만 1회 센다
                    #스윕 모드의 헛돔 1회는 한 바퀴(근거리 약 2초)다. 메모리 모드는
                    #반복이 0.1초라 그대로 세면 nohit(기본 2)를 0.2초에 채워서
                    #새로고침 키를 난타한다. 시간 기준으로 맞춰 둔다


#pit.json 에서 읽는다. (opts, 파일있었나)
def loadpit(path=None):
    if path == None:
        path = PIT_PATH
    opts = dict(DEFAULT_PIT)
    if not os.path.isfile(path):
        return opts, False
    try:
        f = open(path, 'r', encoding='utf-8')
        data = json.load(f)
        f.close()
    except Exception as e:
        log('메모리 설정 불러오기 실패, 기본값 사용 : ' + str(e))
        return opts, False

    #아는 키만, 값이 이상하면 기본값을 유지한다 (main.loadconfig 와 같은 방식)
    if isinstance(data.get('mem'), bool):
        opts['mem'] = data['mem']
    if isinstance(data.get('target'), bool):
        opts['target'] = data['target']
    for key in ('hp_pct', 'mp_pct'):
        try:
            v = int(data.get(key, opts[key]))
            if 0 <= v <= 100:
                opts[key] = v
        except (TypeError, ValueError):
            pass
    raw = data.get('clans')
    if isinstance(raw, list):
        opts['clans'] = [str(x).strip() for x in raw if str(x).strip() != '']
    return opts, True


def savepit(opts, path=None):
    if path == None:
        path = PIT_PATH
    data = {'mem':    bool(opts.get('mem',    DEFAULT_PIT['mem'])),
            'hp_pct': int(opts.get('hp_pct',  DEFAULT_PIT['hp_pct'])),
            'mp_pct': int(opts.get('mp_pct',  DEFAULT_PIT['mp_pct'])),
            'clans':  list(opts.get('clans',  [])),
            'target': bool(opts.get('target', DEFAULT_PIT['target']))}
    try:
        f = open(path, 'w', encoding='utf-8')
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.close()
        return True
    except Exception as e:
        log('메모리 설정 저장 실패 : ' + str(e))
        return False


def applypit(opts):
    global MEM_ON, HP_PCT, MP_PCT, CLANS, TARGET_ON
    MEM_ON    = bool(opts.get('mem',    DEFAULT_PIT['mem']))
    HP_PCT    = int(opts.get('hp_pct',  DEFAULT_PIT['hp_pct']))
    MP_PCT    = int(opts.get('mp_pct',  DEFAULT_PIT['mp_pct']))
    TARGET_ON = bool(opts.get('target', DEFAULT_PIT['target']))
    CLANS     = [str(x).strip() for x in opts.get('clans', []) if str(x).strip() != '']


#=====================================================================
# 메모리 상태
#=====================================================================

#메모리로 읽을 수 있는 상태인지. 한 번 죽으면(stale) 이 세션에서는 다시 안 쓴다
def memready():
    return MEM_ON and MEM != None and MEM.attached() and not MEM.stale


#이 세션에서 메모리 감지를 포기한다
def memoff(why):
    if MEM != None and not MEM.stale:
        MEM.stale = True
        log('메모리 감지 중단 - 이미지/스윕으로 전환 : ' + why)


#객체 목록을 쓸 수 있는지 (base/stride 를 안 채웠으면 못 쓴다)
def objready():
    if not memready():
        return False
    o = MEM.cfg.get('objlist') or {}
    return mr.num(o.get('base')) != None and mr.num(o.get('stride')) != None


#월드->스크린 변환이 쓸 수 있는 상태인지 (memcalib.py 로 채운다)
#screenmat() 으로 보면 '없는 경우' 와 '모양이 깨진 경우' 를 같이 걸러낸다.
#깨진 걸 통과시키면 타겟이 늘 0개로 나와서 새로고침만 반복하게 된다
def screenready():
    return objready() and TARGET_ON and MEM.screenmat() != None


def backend():
    if not MEM_ON:
        return '이미지 (메모리 끔)'
    if not memready():
        return '이미지 폴백 (메모리 못 씀)'
    parts = ['HP']
    if objready():
        parts.append('혈맹')
    if screenready():
        parts.append('타겟')
    return '메모리 : ' + '+'.join(parts)


#=====================================================================
# 감지 : 전부 3상태다. True / False / None(판단 못 함 -> 폴백)
#=====================================================================

#피가 임계 아래인가
def hplow():
    if not memready():
        return None
    pct = MEM.hppct()
    if pct == None:
        return None
    if pct <= HP_PCT:
        log('피 ' + '%.1f%%' % pct + ' <= ' + str(HP_PCT) + '% 귀환!')
        return True
    return False


#마나가 임계 아래인가. MP_PCT 가 0 이면 안 본다
def mplow():
    if MP_PCT <= 0 or not memready():
        return False
    pct = MEM.mppct()
    if pct == None:
        return False
    if pct <= MP_PCT:
        log('마나 ' + '%.1f%%' % pct + ' <= ' + str(MP_PCT) + '% 귀환!')
        return True
    return False


#적대 혈맹이 보이는가. (판단했나, 찾은객체 or None)
def hostile():
    if not objready():
        return False, None
    #player_types 를 안 채웠으면 플레이어를 구분할 수 없다
    if not ((MEM.cfg.get('objlist') or {}).get('player_types')):
        return False, None

    objs = MEM.objects()
    plrs = MEM.players(objs)
    #내 캐릭터도 플레이어이므로 목록이 비는 건 '아무도 없다' 가 아니라 '잘못 읽고 있다' 다.
    #그대로 '적대 없음' 으로 넘기면 도망 기능이 조용히 죽는다. 이미지 마크로 넘긴다
    if len(objs) == 0 or len(plrs) == 0:
        return False, None

    me = MEM.selfid()
    for o in plrs:
        if me != None and o.get('id') == me:      #나는 건너뛴다. 좌표가 아니라 id 로 정확히
            continue
        clan = (o.get('clan') or '').strip()
        if clan == '':                            #혈맹 없는 캐릭터는 적대로 안 본다
            continue
        if clan in CLANS:
            continue
        return True, o
    return True, None


#=====================================================================
# 피 / 마크 감시 (타이머 스레드)
#=====================================================================

def checkrHp():
    if not main.ALIVE:
        return
    try:
        _checkrHp()
    except Exception as e:
        log('피/마크 감시 오류 : ' + str(e))
        log(traceback.format_exc())
        main._arm(main.HP_INTERVAL, checkrHp)
        return


def _checkrHp():
    #--- 1. 피 ---
    low = hplow()
    if low == None:
        #메모리를 못 읽었다. main.py 와 똑같이 경고 UI 이미지를 본다
        if main.gu.locateCenterOnScreen(main.IMAGE_DIR + main.HP_IMG,
                                        confidence=main.HP_CONF) != None:
            log('피 소모 완료 귀환! (이미지)')
            main.request('return')
            return
    elif low:
        main.request('return')
        return

    #--- 2. 마나 ---
    if mplow():
        main.request('return')
        return

    #--- 3. 적대 혈맹 ---
    done, who = hostile()
    if done:
        if who != None:
            log('적대 혈맹 발견 : ' + str(who.get('clan')) + ' / '
                + str(who.get('name')) + ' @ ' + str(who.get('x')) + ',' + str(who.get('y'))
                + ' 귀환!')
            main.request('return')
            return
    else:
        #메모리로 못 봤다. main.py 의 마크 템플릿 매칭을 그대로 쓴다
        marks = main.markfiles()
        hay   = main.screengrab() if (main.MARK_BG_TOL > 0 and main.MASK_OK
                                      and len(marks) > 0) else None
        for markpath in marks:
            markname = os.path.basename(markpath)
            markconf = main.MARK_CONF_BY_FILE.get(markname, main.MARK_CONF)
            found    = main.findmark(hay, markpath, markconf)
            if found != None:
                log('적대 마크 발견 (' + markname + ' @ '
                    + str(found[0]) + ',' + str(found[1]) + ') 귀환!')
                main.request('return')
                return

    main._arm(main.HP_INTERVAL, checkrHp)


#=====================================================================
# 타겟 집기
#=====================================================================

#화면 크기. 변환 결과가 화면 밖이면 찍어볼 필요가 없다
def screensize():
    global SCREEN
    if SCREEN == None:
        try:
            SCREEN = tuple(main.gu.size())
        except Exception:
            SCREEN = (1920, 1080)
    return SCREEN


#가까운 몹부터 (화면좌표, 객체) 목록으로. 변환이 없거나 몹이 없으면 빈 목록
#cool 에 든 id (찍었는데 커서가 아니었던 몹) 는 건너뛴다
def picktargets(cool):
    if not screenready():
        return []
    me = MEM.selfpos()
    if me == None:
        return []

    now = time.time()
    #지난 항목은 지운다 (긴 세션에서 계속 쌓이면 안 된다)
    for oid in [k for k, v in cool.items() if v <= now]:
        del cool[oid]

    got = MEM.screenmat()
    if got == None:
        return []
    mat, og = got

    rows = []
    for o in MEM.mobs():
        oid = o.get('id')
        if oid in cool and cool[oid] > now:
            continue
        x = o.get('x')
        y = o.get('y')
        if not isinstance(x, int) or not isinstance(y, int):
            continue
        #hp 필드를 읽을 수 있으면 죽은 몹은 건너뛴다
        hp = o.get('hp')
        if isinstance(hp, int) and hp == 0:
            continue
        d = (x - me[0]) ** 2 + (y - me[1]) ** 2
        rows.append((d, o))

    rows.sort(key=lambda r: r[0])

    #변환은 위에서 한 번 읽은 me / mat 로 직접 계산한다.
    #MEM.toscreen() 을 몹마다 부르면 내 좌표를 그때그때 다시 읽어서,
    #한 바퀴 도는 동안 캐릭터가 움직이면 타겟 좌표들이 서로 어긋난다
    sw, sh = screensize()
    out = []
    for d, o in rows:
        dx = o.get('x') - me[0]
        dy = o.get('y') - me[1]
        sx = int(round(og[0] + mat[0][0] * dx + mat[0][1] * dy))
        sy = int(round(og[1] + mat[1][0] * dx + mat[1][1] * dy))
        if not (0 <= sx < sw and 0 <= sy < sh):     #화면 밖이면 건너뛴다
            continue
        out.append(((sx, sy), o))
        if len(out) >= MEM_TRY:                    #가까운 순이므로 채워지면 끝
            break
    return out


#=====================================================================
# 사냥 루프 (매크로 스레드)
#   main.huntloop 과 뼈대는 같다. 스캔점을 소비하는 부분만 타겟 집기로 갈린다
#=====================================================================

def huntloop(p, atkvalue):
    points  = main._scanpoints(p)
    parkpos = (p[0], p[1] + main.SCAN_START * main.SCAN_FAR + main.PARK_GAP)
    cnt     = 0       #헛돈 횟수 (칼질하면 초기화)
    loopcnt = 0       #누적 루프 횟수
    idx     = 0       #스윕용 스캔점 번호
    miss    = 0       #메모리 좌표가 연속으로 빗나간 횟수
    cool    = {}      #몹 id -> 이 시각까지 건너뛴다
    nomob   = 0.0     #'몹 없음' 을 마지막으로 센 시각

    skillon  = main.ATTACK_ON and main.KEY_SKILL != None and main.SKILL_COOL > 0
    skillsec = float(main.SKILL_COOL)
    tick     = time.perf_counter()

    def useskill(why):
        if skillon and skillsec >= main.SKILL_COOL:
            log('스킬 ' + main.KEY_SKILL.upper() + ' (' + why + ')')
            main.gu.press(main.KEY_SKILL, presses=1)
            return True
        return False

    if main.ATTACK_ON:
        if screenready():
            log('타겟 : 메모리 몹 목록 (가까운 ' + str(MEM_TRY) + '마리까지 시도)')
            log('       좌표를 찍고도 커서가 대상이 아니면 클릭하지 않는다')
        else:
            radii = ','.join(str(main.SCAN_START * (i + 1)) for i in range(main.SCAN_ROUND))
            log('서치 : ' + ('근거리' if main.SCAN_ROUND <= main.SCAN_NEAR else '원거리')
                + '  ' + str(main.SCAN_DIRS) + '방향 x ' + str(main.SCAN_ROUND) + '바퀴'
                + '  반지름 ' + radii + '  총 ' + str(len(points)) + '점')
        log('파크 : ' + str(parkpos[0]) + ',' + str(parkpos[1]))

    if skillon:
        log('공격스킬 : ' + main.KEY_SKILL.upper() + '  쿨타임 '
            + str(main.SKILL_COOL) + '초 (공격 중에만 흐름)')

    main.settrigger('hunt')
    while main.ALIVE:
        if main.runpending():
            tick = time.perf_counter()
            continue

        #공격 꺼짐 : 수동 사냥 보조 (main.py 와 동일)
        if not main.ATTACK_ON:
            if main.win32gui.GetCursorInfo()[1] == atkvalue:
                main.gu.middleClick()
                time.sleep(main.MANUAL_CLICK_GAP)
            else:
                time.sleep(main.MANUAL_POLL)
            continue

        now       = time.perf_counter()
        skillsec += now - tick
        tick      = now

        #칼질 소리가 들리면 이미 잡고 있는 것이므로 커서를 안 건드린다
        if main.FIGHT_READY and main.FIGHTING:
            if useskill('칼질 중'):
                skillsec = 0.0
            time.sleep(main.FIGHT_POLL)
            continue

        #--- 메모리 경로 : 몹 목록에서 좌표를 집어 바로 찍는다 ---
        if screenready():
            targets = picktargets(cool)

            if len(targets) == 0:
                #목록에 몹이 없다 = 헛돈 것. 단 NOMOB_SEC 간격으로만 센다
                #(스윕의 '1바퀴 헛돔' 과 시간 척도를 맞춘다)
                nowt = time.time()
                if nowt - nomob >= NOMOB_SEC:
                    nomob    = nowt
                    cnt     += 1
                    loopcnt += 1
                    if main.KEY_REFRESH != None and (cnt >= main.NOHIT_LIMIT
                                                     or loopcnt >= main.LOOP_LIMIT):
                        log('새로고침 : ' + main.KEY_REFRESH + '  (몹 없음 ' + str(cnt)
                            + '/' + str(main.NOHIT_LIMIT) + ', 누적 ' + str(loopcnt)
                            + '/' + str(main.LOOP_LIMIT) + ')')
                        main.gu.press(main.KEY_REFRESH, presses=1)
                        cnt     = 0
                        loopcnt = 0
                time.sleep(main.FIGHT_POLL)
                continue

            hit = False
            for sp, o in targets:
                #스윕과 달리 지터를 주지 않는다. 메모리가 준 좌표는 정확한데 ±6px 흔들면
                #작은 몹에서 빗나가 쓸데없이 쿨다운만 쌓인다. 사람처럼 보이게 하는 흔들기는
                #_settleclick 의 CLICK_ADJ 가 클릭 직전에 이미 한다
                x, y = sp

                main._movefast(parkpos[0], parkpos[1])      #커서 초기화 (park)
                time.sleep(main.PROBE_SETTLE * main.random.uniform(*main.PROBE_JITTER)
                           if main.NATURAL_ON else main.PROBE_SETTLE)

                #여기가 안전장치다. 메모리가 준 좌표라도 커서가 대상이 아니면 안 찍는다
                if main._probe(x, y, atkvalue):
                    main._settleclick(x, y, atkvalue)
                    if useskill('공격 후'):
                        skillsec = 0.0
                    cnt  = 0
                    miss = 0
                    cool.clear()
                    hit  = True
                    break
                else:
                    #이 몹은 잠깐 건너뛴다 (벽 뒤거나 변환이 살짝 어긋난 자리)
                    oid = o.get('id')
                    if oid != None:
                        cool[oid] = time.time() + COOL_SEC

            if not hit:
                miss += 1
                if miss >= MISS_LIMIT:
                    memoff('타겟 좌표가 ' + str(miss) + '회 연속 빗나감'
                           + ' - 변환(screen)이나 오프셋을 다시 맞춰야 한다')
                    miss = 0
                    idx  = 0
            continue

        #--- 폴백 경로 : main.py 와 완전히 같은 커서 스윕 ---
        x, y = points[idx]
        idx += 1

        if idx >= len(points):
            idx      = 0
            cnt     += 1
            loopcnt += 1
            if main.KEY_REFRESH != None and (cnt >= main.NOHIT_LIMIT
                                             or loopcnt >= main.LOOP_LIMIT):
                log('새로고침 : ' + main.KEY_REFRESH
                    + '  (헛돔 ' + str(cnt) + '/' + str(main.NOHIT_LIMIT)
                    + ', 누적 ' + str(loopcnt) + '/' + str(main.LOOP_LIMIT) + ')')
                main.gu.press(main.KEY_REFRESH, presses=1)
                cnt     = 0
                loopcnt = 0

        if main.NATURAL_ON:
            x += main.random.randint(-main.SCAN_JITTER, main.SCAN_JITTER)
            y += main.random.randint(-main.SCAN_JITTER, main.SCAN_JITTER)

        main._movefast(parkpos[0], parkpos[1])
        time.sleep(main.PROBE_SETTLE * main.random.uniform(*main.PROBE_JITTER)
                   if main.NATURAL_ON else main.PROBE_SETTLE)
        if main._probe(x, y, atkvalue):
            main._settleclick(x, y, atkvalue)
            if useskill('공격 후'):
                skillsec = 0.0
            cnt = 0
            if not main.FIGHT_READY:
                idx = 0


#=====================================================================
# 매크로 본체 (main.runmacro 와 같은 순서. 감시/루프만 이 파일 것을 쓴다)
#=====================================================================

def runmacro():
    global MEM
    try:
        main.ALIVE  = True
        main.HOTKEY = main.k.add_hotkey('tab', main.requeststop)
        log('tab 키를 누르면 정지')

        #--- 메모리 붙기 ---
        if MEM_ON:
            if not mr.IS_WIN:
                log('메모리 감지는 Windows 에서만 된다 - 이미지로 돈다')
            else:
                MEM = mr.Mem(MEM_PATH, log)
                if not MEM.attach():
                    log('메모리 붙기 실패 : ' + str(MEM.err))
                    log('이미지 폴백으로 계속 돈다 (python memprobe.py 로 원인 확인)')
                    MEM.stale = True
                else:
                    if not objready():
                        log('objlist 미설정 - 혈맹 판별은 마크 이미지로 돈다')
                    if objready() and not screenready():
                        log('screen 변환 미설정 - 타겟은 커서 스윕으로 돈다'
                            + ' (python memcalib.py 로 맞춘다)')
        log('감지 방식 : ' + backend())

        for i in range(main.START_DELAY, 0, -1):
            log('게임 창을 활성화하세요... ' + str(i))
            time.sleep(1)
            if main.runpending() or (not main.ALIVE):
                return

        atk = main.setattckinfo(main.CENTERPOINT)
        log('공격 커서 : ' + str(atk))
        if not main.ATTACK_ON:
            log('공격 끔 - 수동 사냥 : 대상 위에 커서를 올리면 휠 클릭을 대신 누릅니다')

        if main.KEY_TRANSFORM != None and main.TRANSFORM_INTERVAL > 0:
            log('변신(' + main.KEY_TRANSFORM + ') ' + str(main.TRANSFORM_INTERVAL) + '초 주기')
            main.transformtimer()
        else:
            log('변신 미지정 - 변신 끔')

        main.startbuffs()

        log('채팅버프(' + main.CHAT_CMD + ') ' + str(main.CHAT_INTERVAL) + '초 주기')
        main.chatbufftimer()

        if main.KEY_RETURN != None:
            log('귀환(' + main.KEY_RETURN + ') - 피 감시 시작')
            checkrHp()                      #이 파일 것을 쓴다
        else:
            log('귀환키 미지정 - 피 감시 끔')

        if main.KEY_REFRESH == None:
            log('새로고침키 미지정 - 새로고침 끔')

        if main.SOUND_ON:
            t = threading.Thread(target=main.soundwatch)
            t.daemon = True
            t.start()
        else:
            log('소리 감지 끔 - 서치를 계속 돕니다')

        main.HUNT_START = time.time()
        log('사냥 시작')
        huntloop([main.CENTERPOINT[0], main.CENTERPOINT[1] + main.SCAN_OFFSET_Y], atk)
    except Exception as e:
        log('매크로 오류 : ' + str(e))
        log(traceback.format_exc())
    finally:
        main.ALIVE = False
        main.canceltimers()
        if MEM != None:
            MEM.detach()
        if main.HUNT_START != None:
            log('사냥 시간 : ' + main.fmtsec(time.time() - main.HUNT_START)
                + ' (' + time.strftime('%H:%M:%S', time.localtime(main.HUNT_START)) + ' 시작)')
            main.HUNT_START = None
        else:
            log('사냥 시작 전 종료')
        if main.HOTKEY != None:
            try:
                main.k.remove_hotkey(main.HOTKEY)
            except Exception:
                pass
            main.HOTKEY = None
        main.settrigger(None)
        log('매크로 종료')


#=====================================================================
# GUI : main.App 을 상속해서 메모리 칸만 더한다
#=====================================================================

tk  = main.tk
ttk = main.ttk


class App(main.App):
    def __init__(self, root):
        main.App.__init__(self, root)        #기존 UI 전부 그대로
        root.title('사냥 매크로 (메모리)')
        self._buildmem(root)
        opts, found = loadpit()
        self.setmemform(opts)
        log(('메모리 설정 불러옴 : ' + PIT_PATH) if found
            else '메모리 설정 없음 - 기본값 사용 (메모리 감지 꺼짐)')
        log('mem.json : ' + (MEM_PATH if os.path.isfile(MEM_PATH) else '없음 - ' + MEM_PATH))

    #메모리 칸을 시작 버튼 바로 앞에 꽂는다
    #(main.App.__init__ 이 위젯을 순서대로 쌓는 구조라 중간 삽입은 before= 로 한다)
    def _buildmem(self, root):
        box = ttk.LabelFrame(root, text='메모리 감지 (핏빛서버)')
        box.pack(fill='x', padx=10, pady=(8, 0), before=self.btn)

        self.memon = tk.BooleanVar(value=DEFAULT_PIT['mem'])
        self.memchk = ttk.Checkbutton(box, text='메모리에서 상태 읽기 (끄면 지금 main.py 와 동일)',
                                      variable=self.memon)
        self.memchk.pack(anchor='w', padx=6, pady=(4, 0))

        self.tgton = tk.BooleanVar(value=DEFAULT_PIT['target'])
        self.tgtchk = ttk.Checkbutton(box, text='몹 목록으로 타겟 집기 (끄면 커서 스윕 유지)',
                                      variable=self.tgton)
        self.tgtchk.pack(anchor='w', padx=6, pady=(0, 4))

        #--- HP / MP 임계 ---
        row = ttk.Frame(box)
        row.pack(fill='x', padx=6, pady=(2, 0))
        ttk.Label(row, text='귀환 임계', width=12).pack(side='left')
        ttk.Label(row, text='피').pack(side='left')
        self.hppct = tk.StringVar(value=str(DEFAULT_PIT['hp_pct']))
        self.hpent = ttk.Entry(row, textvariable=self.hppct, width=5, justify='center')
        self.hpent.pack(side='left', padx=(4, 2))
        ttk.Label(row, text='%   마나').pack(side='left')
        self.mppct = tk.StringVar(value=str(DEFAULT_PIT['mp_pct']))
        self.mpent = ttk.Entry(row, textvariable=self.mppct, width=5, justify='center')
        self.mpent.pack(side='left', padx=(4, 2))
        ttk.Label(row, text='%  (마나 0 = 안 봄)', foreground='#555').pack(side='left')

        #--- 혈맹 화이트리스트 ---
        row2 = ttk.Frame(box)
        row2.pack(fill='x', padx=6, pady=(4, 0))
        ttk.Label(row2, text='내 혈맹', width=12).pack(side='left')
        self.clans = tk.StringVar(value='')
        self.clent = ttk.Entry(row2, textvariable=self.clans)
        self.clent.pack(side='left', fill='x', expand=True)

        ttk.Label(box, foreground='#555',
                  text='쉼표로 여러 개. 여기 적지 않은 혈맹이 주변에 보이면 귀환합니다.\n'
                       '혈맹명은 python memprobe.py --objs 로 확인한 문자열을 그대로 넣으세요.\n'
                       '오프셋은 mem.json 에 있습니다. 먼저 python memprobe.py 로 읽기가 되는지 확인하세요.'
                  ).pack(anchor='w', padx=6, pady=(2, 6))

    #--- 폼 <-> 값 ---

    def setmemform(self, opts):
        self.memon.set(bool(opts.get('mem', DEFAULT_PIT['mem'])))
        self.tgton.set(bool(opts.get('target', DEFAULT_PIT['target'])))
        self.hppct.set(str(opts.get('hp_pct', DEFAULT_PIT['hp_pct'])))
        self.mppct.set(str(opts.get('mp_pct', DEFAULT_PIT['mp_pct'])))
        self.clans.set(', '.join(opts.get('clans', [])))

    #숫자가 아니거나 범위를 벗어나면 None
    def readmemform(self):
        out = {'mem': self.memon.get(), 'target': self.tgton.get()}
        for key, var, label in (('hp_pct', self.hppct, '피'),
                                ('mp_pct', self.mppct, '마나')):
            raw = var.get().strip()
            if raw == '':
                raw = '0'
            if not raw.isdigit() or int(raw) > 100:
                log('귀환 임계는 0~100 정수만 : ' + label + ' = ' + raw)
                return None
            out[key] = int(raw)
        out['clans'] = [x.strip() for x in self.clans.get().split(',') if x.strip() != '']
        return out

    #--- 버튼 ---

    def onsave(self):
        seconds, roles, opts = self.readform()
        if seconds == None:
            return
        mopts = self.readmemform()
        if mopts == None:
            return
        if main.saveconfig(seconds, roles, opts):
            log('설정 저장 : ' + main.CONFIG_PATH)
        if savepit(mopts):
            log('메모리 설정 저장 : ' + PIT_PATH)

    def onload(self):
        main.App.onload(self)
        mopts, found = loadpit()
        self.setmemform(mopts)
        log(('메모리 설정 불러옴 : ' + PIT_PATH) if found
            else '메모리 설정 파일 없음 - 기본값으로 되돌림')

    def ondefault(self):
        main.App.ondefault(self)
        self.setmemform(dict(DEFAULT_PIT))

    def _memwidgets(self):
        return (self.memchk, self.tgtchk, self.hpent, self.mpent, self.clent)

    def lockui(self):
        main.App.lockui(self)
        for b in self._memwidgets():
            b.configure(state='disabled')

    def unlockui(self):
        main.App.unlockui(self)
        for b in self._memwidgets():
            b.configure(state='normal')

    def onstart(self):
        if self.started:
            return

        seconds, roles, opts = self.readform()
        if seconds == None:
            log('시작 실패 - 주기 값을 확인하세요')
            return
        mopts = self.readmemform()
        if mopts == None:
            log('시작 실패 - 메모리 설정 값을 확인하세요')
            return

        main.saveconfig(seconds, roles, opts)
        main.applyconfig(seconds, roles, opts)
        savepit(mopts)
        applypit(mopts)

        log('=== 설정 ===')
        log('  공격 : ' + ('사용' if opts['attack'] else '끔'))
        log('  칼 탐지 거리 : ' + dict(main.RANGES)[opts['range']]
            + ' (반지름 ' + str(main.SCAN_START) + '~'
            + str(main.SCAN_START * main.SCAN_ROUND) + 'px)')
        log('  새로고침 트리거 : ' + str(opts['nohit']) + '회 헛돌면')
        log('  소리 감지 : ' + ('사용' if opts.get('sound') else '끔'))
        for rid, label in main.ROLES:
            log('  ' + label + ' : ' + (roles[rid].upper() if roles[rid] else '미지정'))
        act = [(n, key, s) for n, key, s in main.BUFFS if s > 0]
        if act:
            for n, key, s in act:
                log('  버프 ' + key.upper() + ' : ' + str(s) + '초')
        else:
            log('  버프 : 없음')
        log('=== 메모리 ===')
        log('  메모리 감지 : ' + ('사용' if MEM_ON else '끔'))
        log('  귀환 임계 : 피 ' + str(HP_PCT) + '%'
            + ('  마나 ' + str(MP_PCT) + '%' if MP_PCT > 0 else '  마나 안 봄'))
        log('  타겟 집기 : ' + ('사용' if TARGET_ON else '끔 (커서 스윕)'))
        log('  내 혈맹 : ' + (', '.join(CLANS) if CLANS else '없음 (혈맹 판별 안 함)'))
        if MEM_ON and len(CLANS) == 0:
            log('  ! 내 혈맹을 안 적으면 보이는 모든 혈맹이 적대로 잡혀 바로 귀환한다')

        self.started = True
        self.lockui()
        self.thread = threading.Thread(target=runmacro, daemon=True)
        self.thread.start()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
