import time
import win32gui
import win32api
import pyautogui as gu
# import schedule as sc     #등록된 작업이 없어서 사용 안 함
import keyboard as k
import time
import threading
import queue
import json
import math
import os.path
import sys
import tkinter as tk
from tkinter import ttk

#실행 폴더 : exe 로 묶으면 exe 가 놓인 폴더, 아니면 스크립트 폴더
#(콘솔/exec 실행이라 __file__ 이 없을 때는 argv[0] -> cwd 순으로 폴백)
def _appdir():
    if getattr(sys, 'frozen', False):        #PyInstaller 로 만든 exe
        return os.path.dirname(os.path.realpath(sys.executable))
    try:
        return os.path.dirname(os.path.realpath(__file__))
    except NameError:
        return os.path.dirname(os.path.realpath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()

APP_DIR = _appdir()

#이미지 폴더 : exe 옆의 image\ 를 먼저 본다 (해상도마다 다시 찍어야 하므로 밖에 두는 게 낫다)
#없으면 exe 안에 묶어둔 것을 쓴다
def _imagedir():
    outside = os.path.join(APP_DIR, 'image')
    if os.path.isdir(outside):
        return outside + os.sep
    bundled = getattr(sys, '_MEIPASS', None)     #exe 안에 풀린 임시 폴더
    if bundled != None and os.path.isdir(os.path.join(bundled, 'image')):
        return os.path.join(bundled, 'image') + os.sep
    return outside + os.sep

IMAGE_DIR   = _imagedir()
CONFIG_PATH = os.path.join(APP_DIR, 'config.json')

#최신 pyautogui 는 이미지 못 찾으면 None 대신 ImageNotFoundException 을 던짐
#아래 코드 전체가 None 비교를 전제로 하므로 예전 동작(None 반환)으로 되돌림
gu.useImageNotFoundException(False)

#=====================================================================
# 고정 설정 (UI 에 안 올린 값들. 실기에서 조정)
#=====================================================================
CENTERPOINT = [625, 480]

PROBE_SETTLE = 0.025   # 커서 모양 갱신 대기 최대치(초)
PROBE_STEP   = 0.003   # 폴링 간격(초)
CTRL_DELAY   = 0.08    # ctrl 누른 뒤 클릭까지(초)

#서치 범위 : 센터포인트 기준 SCAN_DIRS 방향을 SCAN_GAP 씩 넓혀가며 SCAN_ROUND 바퀴
SCAN_DIRS  = 16    # 방향 수. 16 이면 22.5도 간격
SCAN_START = 70    # 1바퀴 반지름(px)
SCAN_GAP   = 25    # 바퀴 간 간격(px). SCAN_ROUND 가 2 이상일 때만 쓰인다
SCAN_ROUND = 1     # 총 바퀴 수 -> 반지름 70 한 단계만

BUFF_GAP    = 1    #버프 키 누른 뒤 대기(초)
NOHIT_LIMIT = 5    #이 횟수만큼 헛돌면 새로고침
HP_INTERVAL = 1    #피/마크 감시 주기(초)
START_DELAY = 3    #시작 버튼 누르고 게임 창 활성화할 시간(초)

HP_IMG    = 'checkhp.PNG'   #피 부족 경고 UI
HP_CONF   = 0.8
MARK_IMG  = 'mark1.PNG'     #적대 혈맹 마크
MARK_CONF = 0.7            #마크는 배경에 묻혀서 신뢰도를 낮게 잡는다 (구버전 oman.py 값)

#=====================================================================
# 로그 : 매크로 스레드에서 찍고 GUI 스레드가 꺼내 뿌린다
# tkinter 는 스레드 안전하지 않아서 위젯을 직접 건드리지 않는다
#=====================================================================
LOGQ = queue.Queue()

def log(msg):
    line = time.strftime('%H:%M:%S') + '  ' + str(msg)
    try:
        LOGQ.put_nowait(line)
    except Exception:
        pass
    try:
        print(line)      #exe(--windowed) 는 콘솔이 없어서 stdout 이 None 이다
    except Exception:
        pass

#=====================================================================
# 런타임 설정 : GUI 가 시작 전에 채운다
#=====================================================================
FKEYS = ['f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12']

#기본 셋팅 : config.json 이 없을 때 이 값으로 시작한다
DEFAULT_SECONDS = {
    'f5':     0,   #새로고침 - 주기 없음
    'f6':  1800,
    'f7':  1800,
    'f8':     0,
    'f9':     0,
    'f10':  600,
    'f11': 1800,   #변신 주기
    'f12':    0,   #귀환 - 주기 없음
}
DEFAULT_ROLES = {
    'return':    'f12',
    'refresh':   'f5',
    'transform': 'f11',
}

BUFFS   = []      # [(트리거명, 키, 주기(초))]  주기 0 = 비활성
BUFFKEY = {}      # 트리거명 -> 키

KEY_REFRESH        = None   #사냥 헛돌 때 새로고침
KEY_TRANSFORM      = None   #변신
KEY_RETURN         = None   #귀환
TRANSFORM_INTERVAL = 0      #변신 주기(초). 0 이면 변신 안 함

#=====================================================================
# 트리거 : 한 순간에 하나만 True
#  - TRIGGER 를 바꾸는 것도, 키/마우스를 쓰는 것도 매크로 스레드뿐이다
#  - 타이머 스레드는 PENDING 에 요청만 남기고 물러난다 (마우스 겹침 원천 차단)
#  - GUI 스레드는 입력을 절대 보내지 않는다
#=====================================================================
ALIVE  = False
HOTKEY = None     #tab 핫키 핸들. 정지할 때 떼어낸다

TRIGGER = {'hunt': False, 'stop': False, 'transform': False, 'return': False}
ORDER   = ['stop', 'return', 'transform']   #처리 우선순위 : 정지 > 귀환 > 변신 > 버프

PENDING      = {}                 #타이머 스레드가 채우는 실행 요청
PENDING_LOCK = threading.Lock()

#걸어둔 타이머 목록. 정지할 때 전부 취소한다
#(안 하면 이전 실행의 타이머가 살아남아 재시작한 세션에 요청을 밀어 넣는다)
TIMERS      = []
TIMERS_LOCK = threading.Lock()

def _arm(interval, fn, args=()):
    if not ALIVE:
        return
    t = threading.Timer(interval, fn, args=args)
    t.daemon = True
    with TIMERS_LOCK:
        TIMERS[:] = [x for x in TIMERS if x.is_alive()]   #끝난 것 청소
        TIMERS.append(t)
    t.start()

def canceltimers():
    with TIMERS_LOCK:
        for t in TIMERS:
            t.cancel()
        del TIMERS[:]

#타이머 스레드가 부르는 유일한 함수. 여기서는 절대 키/마우스를 건드리지 않는다
def request(name):
    with PENDING_LOCK:
        PENDING[name] = True

#대기 중인 요청이 있는지만 확인 (스캔 루프에서 빠르게 체크)
def haspending():
    with PENDING_LOCK:
        return len(PENDING) > 0

#우선순위 순으로 하나 꺼낸다
def takepending():
    with PENDING_LOCK:
        for name in ORDER:
            if PENDING.pop(name, False):
                return name
    return None

#전체 False 로 밀고 name 만 True
def settrigger(name):
    for key in TRIGGER:
        TRIGGER[key] = False
    if name != None:
        TRIGGER[name] = True
    log('트리거 : ' + str(name))

#pyautogui 를 거치지 않는 저수준 이동 (PAUSE 우회)
def _movefast(x, y):
    win32api.SetCursorPos((int(x), int(y)))

#(x,y)로 이동 후 공격 커서인지 확인. 맞으면 즉시 True
def _probe(x, y, atkvalue):
    _movefast(x, y)
    deadline = time.perf_counter() + PROBE_SETTLE
    while True:
        if (win32gui.GetCursorInfo()[1] == atkvalue):
            return True
        if time.perf_counter() >= deadline:
            return False
        time.sleep(PROBE_STEP)

#센터포인트 기준 n방향 단위벡터. 12시(위)부터 시계방향으로 균등 분할
#화면 좌표는 y 가 아래로 커지므로 -90도가 12시
def _dirs(n):
    out = []
    for i in range(n):
        a = math.radians(-90.0 + (360.0 / n) * i)
        out.append((math.cos(a), math.sin(a)))
    return out

DIRS = _dirs(SCAN_DIRS)

#한 바퀴(SCAN_DIRS 방향)를 다 돌고 나서 반지름을 SCAN_GAP 만큼 넓혀 다음 바퀴로 간다
#모든 방향이 중심에서 같은 거리에 있다 (구버전은 정사각형이라 대각선이 1.4배 멀었음)
def _scanpoints(p):
    pts  = []
    seen = set()
    for i in range(SCAN_ROUND):
        r = SCAN_START + SCAN_GAP * i
        for dx, dy in DIRS:
            q = (int(round(p[0] + dx * r)), int(round(p[1] + dy * r)))
            if q in seen:      #반올림으로 겹치는 좌표는 버림
                continue
            seen.add(q)
            pts.append(q)
    return pts

#어택 마우스 셋팅
def setattckinfo(centerpoint):
    gu.moveTo(centerpoint[0],centerpoint[1]-200)
    time.sleep(0.1)
    gu.click()
    time.sleep(0.1)
    gu.keyDown('ctrl')
    time.sleep(0.1)
    info = win32gui.GetCursorInfo()[1]
    time.sleep(0.1)
    gu.keyUp('ctrl')
    return info


#한/영 전환. keyboard 라이브러리에 'hangul' 키 이름이 없어서 VK 코드를 직접 쏨
#채팅버프(.버프) 를 빼면서 같이 쉼. 나중에 채팅 입력이 필요하면 되살린다
# VK_HANGUL       = 0x15
# KEYEVENTF_KEYUP = 0x0002
#
# def _togglehangul():
#     win32api.keybd_event(VK_HANGUL, 0, 0, 0)
#     time.sleep(0.05)
#     win32api.keybd_event(VK_HANGUL, 0, KEYEVENTF_KEYUP, 0)
#     time.sleep(0.2)
#
# #채팅창에 ".버프" 입력 (매크로 명령어)
# def sendbuffchat():
#     log('.버프 입력')
#     gu.press('enter', presses=1)        #채팅창 열기
#     time.sleep(0.3)
#     k.write('.버프', delay=0.05)        #유니코드로 직접 주입 (IME 안 거침)
#     time.sleep(0.3)
#     gu.press('enter', presses=1)        #전송

#=====================================================================
# 실행부 : 전부 매크로 스레드에서만 돈다
#=====================================================================

#버프 : F키 한 번
def dobuff(name):
    key = BUFFKEY[name]
    log(name + ' 버프 : ' + key)
    gu.press(key, presses=1)
    time.sleep(BUFF_GAP)

#변신
def dotransform():
    log('변신 : ' + str(KEY_TRANSFORM))
    gu.press(KEY_TRANSFORM, presses=1)
    time.sleep(1)
    file_path = IMAGE_DIR
    lv80 = gu.locateCenterOnScreen(file_path + 'lv80.PNG', confidence=0.8)
    if lv80 != None:
        gu.moveTo(lv80)
        gu.click()
        knight = gu.locateCenterOnScreen(file_path + 'night.PNG', confidence=0.8)
        if knight != None:
            gu.moveTo(knight)
            gu.click()
    else:
        log('변신 메뉴(lv80.PNG) 못 찾음')

#정지 : 키/마우스를 건드리지 않는다. 사냥 루프가 ALIVE 를 보고 빠져나간다
def dostop():
    global ALIVE
    log('정지 - 시작하기를 다시 누르면 재시작')
    ALIVE = False
    canceltimers()

#tab 핫키가 부른다 (keyboard 라이브러리 스레드). 요청만 남긴다
def requeststop():
    if ALIVE:
        request('stop')

#귀환 : 귀환 키만 누르고 정지한다 (프로그램은 안 죽는다)
def doreturn():
    log('귀환 : ' + str(KEY_RETURN))
    gu.press(KEY_RETURN, presses=1)
    dostop()

#대기 중인 트리거 하나를 꺼내 실행. 실행했으면 True
#사냥 트리거 False -> 해당 트리거 True -> 동작 -> 사냥 트리거 True 복귀
def runpending():
    name = takepending()
    if name == None:
        return False

    settrigger(name)              #사냥 트리거는 여기서 자동으로 False
    if name == 'stop':
        dostop()
        return True               #사냥 트리거 복구 안 함. ALIVE=False 로 루프가 끝난다
    if name == 'return':
        doreturn()                #안에서 dostop() 을 부른다
        return True
    if name == 'transform':
        dotransform()
    else:
        dobuff(name)
    settrigger('hunt')            #끝나면 사냥 트리거 복구
    return True

#=====================================================================
# 타이머 : request() 와 재등록 외에는 아무것도 하지 않는다
#=====================================================================

def bufftimer(name, interval):
    if not ALIVE:
        return
    request(name)
    _arm(interval, bufftimer, args=(name, interval))

#활성 슬롯만 즉시 1회 요청하고 타이머 등록
def startbuffs():
    for name, key, interval in BUFFS:
        if interval > 0:
            log(name + '(' + key + ') 버프 ' + str(interval) + '초 주기')
            request(name)
            _arm(interval, bufftimer, args=(name, interval))

def transformtimer():
    if not ALIVE:
        return
    request('transform')
    _arm(TRANSFORM_INTERVAL, transformtimer)

#피 확인. 이미지 매칭은 입력을 안 건드리므로 스레드에서 해도 안전
def checkrHp():
    if not ALIVE:
        return
    file_path = IMAGE_DIR

    #1. 피 부족
    if gu.locateCenterOnScreen(file_path + HP_IMG, confidence=HP_CONF) != None:
        log('피 소모 완료 귀환!')
        request('return')
        return                #매크로 루프가 처리하고 종료하므로 타이머 재등록 안 함

    #2. 적대 혈맹 마크
    if gu.locateCenterOnScreen(file_path + MARK_IMG, confidence=MARK_CONF) != None:
        log('적대 마크 발견 (' + MARK_IMG + ') 귀환!')
        request('return')
        return

    _arm(HP_INTERVAL, checkrHp)

#=====================================================================
# 사냥 루프 (매크로 스레드) - 용던
#=====================================================================
def huntloop(p, atkvalue):
    points  = _scanpoints(p)
    parkpos = (p[0], p[1] + 350)
    cnt     = 0       #클릭 없이 헛돈 횟수

    log('서치 : ' + str(SCAN_DIRS) + '방향 x ' + str(SCAN_ROUND) + '바퀴 (반지름 '
        + str(SCAN_START) + ('' if SCAN_ROUND == 1 else ' 부터 ' + str(SCAN_GAP) + '씩')
        + '), 총 ' + str(len(points)) + '점')

    settrigger('hunt')
    while ALIVE:
        if runpending():       #버프/변신/귀환이 먼저. 처리했으면 처음부터
            continue

        # sc.run_pending()

        cnt += 1
        if cnt >= NOHIT_LIMIT and KEY_REFRESH != None:   #이 횟수만큼 헛돌면 새로고침
            log('새로고침 : ' + KEY_REFRESH)
            gu.press(KEY_REFRESH, presses=1)
            cnt = 0

        for (x, y) in points:
            if (not ALIVE) or haspending():   #버프 대기중이면 스캔 중단하고 바깥에서 처리
                break
            _movefast(parkpos[0], parkpos[1])   #커서 초기화 (park)
            time.sleep(PROBE_SETTLE)
            if _probe(x, y, atkvalue):
                gu.keyDown('ctrl')
                time.sleep(CTRL_DELAY)
                gu.click()
                gu.keyUp('ctrl')
                cnt = 0
                break                       #1바퀴 첫 방향부터 다시 스캔

#=====================================================================
# 설정 저장 / 불러오기 (exe 옆 config.json)
#=====================================================================

#파일에서 읽어 (seconds, roles) 로 돌려준다. 없거나 깨졌으면 기본값
def loadconfig(path=None):
    if path == None:
        path = CONFIG_PATH
    seconds = dict(DEFAULT_SECONDS)
    roles   = dict(DEFAULT_ROLES)
    if not os.path.isfile(path):
        return seconds, roles, False

    try:
        f = open(path, 'r', encoding='utf-8')
        data = json.load(f)
        f.close()
    except Exception as e:
        log('설정 불러오기 실패, 기본값 사용 : ' + str(e))
        return seconds, roles, False

    #모르는 키/이상한 값은 무시하고 아는 것만 받는다
    raw = data.get('seconds', {})
    for key in FKEYS:
        try:
            v = int(raw.get(key, seconds[key]))
            seconds[key] = v if v >= 0 else 0
        except (TypeError, ValueError):
            pass

    raw = data.get('roles', {})
    used = set()
    for rid in ('return', 'refresh', 'transform'):
        v = raw.get(rid)
        #같은 키가 두 역할에 겹치면 뒤엣것을 버린다
        roles[rid] = v if (v in FKEYS and v not in used) else None
        if roles[rid] != None:
            used.add(roles[rid])
    return seconds, roles, True

def saveconfig(seconds, roles, path=None):
    if path == None:
        path = CONFIG_PATH
    data = {'seconds': dict((key, int(seconds.get(key, 0))) for key in FKEYS),
            'roles':   dict((rid, roles.get(rid)) for rid in ('return', 'refresh', 'transform'))}
    try:
        f = open(path, 'w', encoding='utf-8')
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.close()
        return True
    except Exception as e:
        log('설정 저장 실패 : ' + str(e))
        return False

#=====================================================================
# GUI 가 넘긴 설정을 전역에 반영
#=====================================================================
def applyconfig(seconds, roles):
    #seconds : {키 -> 초},  roles : {'return'/'refresh'/'transform' -> 키 or None}
    global BUFFS, BUFFKEY, TRIGGER, ORDER, PENDING
    global KEY_RETURN, KEY_REFRESH, KEY_TRANSFORM, TRANSFORM_INTERVAL

    KEY_RETURN    = roles.get('return')
    KEY_REFRESH   = roles.get('refresh')
    KEY_TRANSFORM = roles.get('transform')

    TRANSFORM_INTERVAL = seconds.get(KEY_TRANSFORM, 0) if KEY_TRANSFORM else 0

    #역할이 지정된 키는 버프 슬롯에서 뺀다
    taken = set(v for v in roles.values() if v)
    BUFFS = []
    for i, key in enumerate(FKEYS):
        if key in taken:
            continue
        BUFFS.append(('buff' + str(i + 1), key, seconds.get(key, 0)))
    BUFFKEY = dict((n, key) for n, key, s in BUFFS)

    TRIGGER = {'hunt': False, 'stop': False, 'transform': False, 'return': False}
    for n, key, s in BUFFS:
        TRIGGER[n] = False
    ORDER = ['stop', 'return', 'transform'] + [n for n, key, s in BUFFS]
    with PENDING_LOCK:
        PENDING = {}

#매크로 본체. GUI 스레드가 아니라 전용 스레드에서 돈다
#끝나면(정지/오류) GUI 가 스레드 종료를 보고 시작 버튼을 다시 켠다
def runmacro():
    global ALIVE, HOTKEY
    try:
        ALIVE  = True
        HOTKEY = k.add_hotkey('tab', requeststop)
        log('tab 키를 누르면 정지')

        for i in range(START_DELAY, 0, -1):
            log('게임 창을 활성화하세요... ' + str(i))
            time.sleep(1)
            #카운트다운 중엔 아직 타이머가 없어서 정지 요청만 들어올 수 있다
            if runpending() or (not ALIVE):
                return

        atk = setattckinfo(CENTERPOINT)
        log('공격 커서 : ' + str(atk))

        if KEY_TRANSFORM != None and TRANSFORM_INTERVAL > 0:
            log('변신(' + KEY_TRANSFORM + ') ' + str(TRANSFORM_INTERVAL) + '초 주기')
            transformtimer()
        else:
            log('변신 미지정 - 변신 끔')

        startbuffs()

        if KEY_RETURN != None:
            log('귀환(' + KEY_RETURN + ') - 피 감시 시작')
            checkrHp()
        else:
            log('귀환키 미지정 - 피 감시 끔')

        if KEY_REFRESH == None:
            log('새로고침키 미지정 - 새로고침 끔')

        huntloop([CENTERPOINT[0], CENTERPOINT[1] - 40], atk)
    except Exception as e:
        log('매크로 오류 : ' + str(e))
    finally:
        #정지든 오류든 여기로 온다. 타이머와 핫키를 반드시 걷어낸다
        ALIVE = False
        canceltimers()
        if HOTKEY != None:
            try:
                k.remove_hotkey(HOTKEY)
            except Exception:
                pass
            HOTKEY = None
        settrigger(None)
        log('매크로 종료')

#=====================================================================
# GUI
#=====================================================================
ROLES = [('return', '귀환'), ('refresh', '새로고침'), ('transform', '변신')]

class App:
    def __init__(self, root):
        self.root    = root
        self.started = False
        self.sec     = {}    #키 -> StringVar (주기)
        self.entry   = {}    #키 -> Entry
        self.note    = {}    #키 -> Label (주기 설명)
        self.role    = {}    #(키, 역할) -> BooleanVar
        self.check   = {}    #(키, 역할) -> Checkbutton
        self.thread  = None  #매크로 스레드. 끝나면 UI 를 다시 연다

        root.title('사냥 매크로')
        root.protocol('WM_DELETE_WINDOW', lambda: os._exit(0))

        #--- 키 설정 표 ---
        box = ttk.LabelFrame(root, text='버프 키 설정 (f5 ~ f12)')
        box.pack(fill='x', padx=10, pady=(10, 4))

        ttk.Label(box, text='키',      width=6,  anchor='center').grid(row=0, column=0, padx=4, pady=4)
        ttk.Label(box, text='주기(초)', width=10, anchor='center').grid(row=0, column=1, padx=4, pady=4)
        for c, (rid, label) in enumerate(ROLES):
            ttk.Label(box, text=label, width=9, anchor='center').grid(row=0, column=2 + c, padx=4, pady=4)
        ttk.Label(box, text='', width=14).grid(row=0, column=5, padx=4)

        for r, key in enumerate(FKEYS, start=1):
            ttk.Label(box, text=key.upper(), width=6, anchor='center').grid(row=r, column=0, padx=4, pady=2)

            var = tk.StringVar(value='0')
            self.sec[key] = var
            ent = ttk.Entry(box, textvariable=var, width=10, justify='center')
            ent.grid(row=r, column=1, padx=4, pady=2)
            self.entry[key] = ent

            for c, (rid, label) in enumerate(ROLES):
                bv = tk.BooleanVar(value=False)
                self.role[(key, rid)] = bv
                cb = ttk.Checkbutton(box, variable=bv,
                                     command=lambda kk=key, rr=rid: self.onrole(kk, rr))
                cb.grid(row=r, column=2 + c, padx=4, pady=2)
                self.check[(key, rid)] = cb

            nl = ttk.Label(box, text='버프 주기', width=14, foreground='#555')
            nl.grid(row=r, column=5, padx=4, pady=2, sticky='w')
            self.note[key] = nl

        ttk.Label(root, foreground='#555',
                  text='귀환 / 새로고침 / 변신 은 각각 키 하나에만 지정됩니다. '
                       '체크한 키 중 변신만 주기를 씁니다.').pack(anchor='w', padx=12)

        #--- 저장 / 불러오기 / 기본값 ---
        cfgbar = ttk.Frame(root)
        cfgbar.pack(fill='x', padx=10, pady=(6, 0))
        self.savebtn = ttk.Button(cfgbar, text='설정 저장',   command=self.onsave)
        self.loadbtn = ttk.Button(cfgbar, text='설정 불러오기', command=self.onload)
        self.defbtn  = ttk.Button(cfgbar, text='기본값',      command=self.ondefault)
        self.savebtn.pack(side='left', expand=True, fill='x', padx=(0, 3))
        self.loadbtn.pack(side='left', expand=True, fill='x', padx=3)
        self.defbtn.pack(side='left', expand=True, fill='x', padx=(3, 0))

        #--- 시작 버튼 ---
        self.btn = ttk.Button(root, text='시작하기', command=self.onstart)
        self.btn.pack(fill='x', padx=10, pady=8)

        #--- 로그 ---
        logbox = ttk.LabelFrame(root, text='로그')
        logbox.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.text = tk.Text(logbox, height=16, width=72, state='disabled', wrap='none')
        sb = ttk.Scrollbar(logbox, orient='vertical', command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')

        #저장된 설정이 있으면 그것으로, 없으면 기본 셋팅으로 시작
        seconds, roles, found = loadconfig()
        self.setform(seconds, roles)
        self.drainlog()
        log(('설정 불러옴 : ' + CONFIG_PATH) if found else '저장된 설정 없음 - 기본 셋팅 사용')

    #--- 폼 <-> 값 ---

    #값을 위젯에 넣는다
    def setform(self, seconds, roles):
        for key in FKEYS:
            self.sec[key].set(str(seconds.get(key, 0)))
            for rid, label in ROLES:
                self.role[(key, rid)].set(roles.get(rid) == key)
        self.refreshrows()

    #위젯에서 값을 읽는다. 주기가 숫자가 아니면 (None, None) 을 돌려준다
    def readform(self):
        seconds = {}
        for key in FKEYS:
            raw = self.sec[key].get().strip()
            if raw == '':
                raw = '0'
            if not raw.isdigit():
                log('주기는 0 이상 정수만 : ' + key.upper() + ' = ' + raw)
                return None, None
            seconds[key] = int(raw)

        roles = {}
        for rid, label in ROLES:
            roles[rid] = None
            for key in FKEYS:
                if self.role[(key, rid)].get():
                    roles[rid] = key
                    break
        return seconds, roles

    def onsave(self):
        seconds, roles = self.readform()
        if seconds == None:
            return
        if saveconfig(seconds, roles):
            log('설정 저장 : ' + CONFIG_PATH)

    def onload(self):
        seconds, roles, found = loadconfig()
        self.setform(seconds, roles)
        log(('설정 불러옴 : ' + CONFIG_PATH) if found
            else '저장된 설정 파일 없음 - 기본 셋팅으로 되돌림')

    def ondefault(self):
        self.setform(dict(DEFAULT_SECONDS), dict(DEFAULT_ROLES))
        log('기본 셋팅으로 되돌림 (저장하려면 설정 저장)')

    #체크박스 하나가 켜지면 같은 역할의 다른 키, 같은 키의 다른 역할을 끈다
    def onrole(self, key, rid):
        if self.role[(key, rid)].get():
            for other in FKEYS:
                if other != key:
                    self.role[(other, rid)].set(False)
            for orid, label in ROLES:
                if orid != rid:
                    self.role[(key, orid)].set(False)
        self.refreshrows()

    def roleof(self, key):
        for rid, label in ROLES:
            if self.role[(key, rid)].get():
                return rid
        return None

    #귀환/새로고침으로 잡힌 키는 주기 입력을 막는다. 변신은 주기를 쓴다
    def refreshrows(self):
        for key in FKEYS:
            rid = self.roleof(key)
            if rid == 'transform':
                self.entry[key].configure(state='normal')
                self.note[key].configure(text='변신 주기')
            elif rid != None:
                self.entry[key].configure(state='disabled')
                self.note[key].configure(text='주기 없음')
            else:
                self.entry[key].configure(state='normal')
                self.note[key].configure(text='버프 주기')

    def lockui(self):
        for key in FKEYS:
            self.entry[key].configure(state='disabled')
            for rid, label in ROLES:
                self.check[(key, rid)].configure(state='disabled')
        for b in (self.savebtn, self.loadbtn, self.defbtn):
            b.configure(state='disabled')
        self.btn.configure(state='disabled', text='동작 중  (tab = 정지)')

    #정지하면 설정을 다시 만질 수 있게 열어준다
    def unlockui(self):
        for key in FKEYS:
            for rid, label in ROLES:
                self.check[(key, rid)].configure(state='normal')
        for b in (self.savebtn, self.loadbtn, self.defbtn):
            b.configure(state='normal')
        self.btn.configure(state='normal', text='시작하기')
        self.refreshrows()      #주기 입력칸은 역할에 따라 다시 결정
        self.started = False
        self.thread  = None

    def onstart(self):
        if self.started:
            return

        seconds, roles = self.readform()
        if seconds == None:
            log('시작 실패 - 주기 값을 확인하세요')
            return

        saveconfig(seconds, roles)     #시작할 때 쓴 설정을 그대로 저장해둔다
        applyconfig(seconds, roles)

        log('=== 설정 ===')
        for rid, label in ROLES:
            log('  ' + label + ' : ' + (roles[rid].upper() if roles[rid] else '미지정'))
        act = [(n, key, s) for n, key, s in BUFFS if s > 0]
        if act:
            for n, key, s in act:
                log('  버프 ' + key.upper() + ' : ' + str(s) + '초')
        else:
            log('  버프 : 없음')

        self.started = True
        self.lockui()
        self.thread = threading.Thread(target=runmacro, daemon=True)
        self.thread.start()

    #매크로 스레드가 넣은 로그를 GUI 스레드에서 꺼내 뿌린다
    #겸사겸사 매크로가 끝났는지 보고 끝났으면 UI 를 다시 연다
    def drainlog(self):
        try:
            while True:
                line = LOGQ.get_nowait()
                self.text.configure(state='normal')
                self.text.insert('end', line + '\n')
                self.text.see('end')
                self.text.configure(state='disabled')
        except queue.Empty:
            pass

        if self.started and self.thread != None and not self.thread.is_alive():
            self.unlockui()

        self.root.after(100, self.drainlog)

if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()

#9시
