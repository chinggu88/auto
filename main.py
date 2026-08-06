import time
import win32gui
import win32api
import pyautogui as gu
# import schedule as sc     #등록된 작업이 없어서 사용 안 함
import keyboard as k
import time
import threading
import os.path
import sys

#이미지 폴더 경로 (콘솔/exec 실행이라 __file__ 이 없을 때는 argv[0] -> cwd 순으로 폴백)
try:
    _BASE_DIR = os.path.dirname(os.path.realpath(__file__))
except NameError:
    _BASE_DIR = os.path.dirname(os.path.realpath(sys.argv[0])) if sys.argv and sys.argv[0] else os.getcwd()
IMAGE_DIR = _BASE_DIR + '\\' + 'image' + '\\'

#최신 pyautogui 는 이미지 못 찾으면 None 대신 ImageNotFoundException 을 던짐
#아래 코드 전체가 None 비교를 전제로 하므로 예전 동작(None 반환)으로 되돌림
gu.useImageNotFoundException(False)

#=====================================================================
# 키 맵 : f5~f12 는 버프 전용이라 기능키는 f1~f4 로 내렸다
# 게임 내 단축키 슬롯도 이 표대로 다시 세팅해야 한다
#=====================================================================
KEY_INNER     = 'f1'    #귀환 후 마무리 메뉴 (기존 f10)
KEY_REFRESH   = 'f5'    #사냥 헛돌 때 새로고침 (기존 f5)
KEY_TRANSFORM = 'f11'    #변신 (기존 f11)
KEY_RETURN    = 'f12'    #귀환 (기존 f12)

#버프 슬롯 : (트리거명, 키, 주기(초))  주기 0 = 비활성(타이머 자체를 안 검)
BUFFS = [
    ('buff1', 'f5',     0),
    ('buff2', 'f6',  1800),
    ('buff3', 'f7',  1800),
    ('buff4', 'f8',     0),
    ('buff5', 'f9',  1800),
    ('buff6', 'f10',  300),
    ('buff7', 'f11',    0),
    ('buff8', 'f12',    0),
]
BUFFKEY = dict((n, key) for n, key, s in BUFFS)

BUFF_GAP           = 1      #버프 키 누른 뒤 대기(초)
NOHIT_LIMIT        = 5    #이 횟수만큼 헛돌면 새로고침
TRANSFORM_INTERVAL = 1200   #변신 주기(초)
HP_INTERVAL        = 1      #피 감시 주기(초)

#=====================================================================
# 트리거 : 한 순간에 하나만 True
#  - TRIGGER 를 바꾸는 것도, 키/마우스를 쓰는 것도 메인 스레드뿐이다
#  - 타이머 스레드는 PENDING 에 요청만 남기고 물러난다 (마우스 겹침 원천 차단)
#=====================================================================
ALIVE = True     #기존 isture. 메인 스레드만 쓴다

TRIGGER = {'hunt': False, 'transform': False, 'return': False}
for _n, _k, _s in BUFFS:
    TRIGGER[_n] = False

#처리 우선순위 : 귀환 > 변신 > 버프1..8
ORDER = ['return', 'transform'] + [n for n, key, s in BUFFS]

PENDING      = {}                 #타이머 스레드가 채우는 실행 요청
PENDING_LOCK = threading.Lock()

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
    print('트리거 : ' + str(name))

#탐색 튜닝값 (실기에서 조정)
PROBE_SETTLE = 0.025   # 커서 모양 갱신 대기 최대치(초)
PROBE_STEP   = 0.003   # 폴링 간격(초)
CTRL_DELAY   = 0.08    # ctrl 누른 뒤 클릭까지(초)

#서치 범위 : 센터포인트 기준 8방향을 SCAN_GAP 씩 넓혀가며 SCAN_ROUND 바퀴
SCAN_START = 70    # 1바퀴 반지름(px)
SCAN_GAP   = 25    # 바퀴 간 간격(px). 일정하게 벌어진다
SCAN_ROUND = 3     # 총 바퀴 수 -> 70 / 95 / 120
# STEPS      = (70, 95, 120)   #구버전 : 반지름을 직접 나열했음

#innerauto 튜닝값
RETURN_WAIT  = 10      # f4 귀환 후 마을 로딩 대기(초)
INNER_IMG1   = 'inner1.PNG'   # f1 누른 뒤 찾을 이미지 (실제 파일명으로 교체)
INNER_IMG2   = 'inner2.PNG'   # 이어서 찾을 이미지 (실제 파일명으로 교체)
INNER_CONF   = 0.8     # 두 이미지 매칭 신뢰도
INNER_TRY    = 10      # 이미지 못 찾을 때 재시도 횟수 (1초 간격)

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

#센터포인트 기준 8방향 (12시부터 시계방향으로 돈다)
DIRS8 = [
    ( 0, -1),   #위
    ( 1, -1),   #오른쪽 위
    ( 1,  0),   #오른쪽
    ( 1,  1),   #오른쪽 아래
    ( 0,  1),   #아래
    (-1,  1),   #왼쪽 아래
    (-1,  0),   #왼쪽
    (-1, -1),   #왼쪽 위
]

#센터포인트 기준 8방향을 한 바퀴 다 돌고 나서 반지름을 SCAN_GAP 만큼 넓혀 다음 바퀴로 간다
#구버전은 좌표를 거리순으로 재정렬해서 바퀴가 섞여 돌았음 (70축->95축->70대각->...)
def _scanpoints(p):
    pts = []
    for i in range(SCAN_ROUND):
        r = SCAN_START + SCAN_GAP * i     #1바퀴 70, 2바퀴 95, 3바퀴 120
        for dx, dy in DIRS8:
            pts.append((p[0] + dx * r, p[1] + dy * r))
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
#     print('.버프 입력')
#     gu.press('enter', presses=1)        #채팅창 열기
#     time.sleep(0.3)
#     k.write('.버프', delay=0.05)        #유니코드로 직접 주입 (IME 안 거침)
#     time.sleep(0.3)
#     gu.press('enter', presses=1)        #전송

#이미지 나올 때까지 재시도하고 찾으면 클릭. 끝내 못 찾으면 False
def _findandclick(name):
    file_path = IMAGE_DIR
    for i in range(0, INNER_TRY):
        pos = gu.locateCenterOnScreen(file_path + name, confidence=INNER_CONF)
        if pos != None:
            gu.moveTo(pos)
            time.sleep(0.3)
            gu.click()
            return True
        time.sleep(1)
    print('innerauto : ' + name + ' 못 찾음')
    return False

#귀환 후 마무리 : f1 -> 이미지1 클릭 -> 이미지2 클릭 -> 스크립트 종료
def innerauto():
    print('innerauto 시작')

    #1. f1 로 메뉴 열기
    gu.press(KEY_INNER, presses=1)
    time.sleep(1)
    #2. 이미지1 찾고 클릭
    if not _findandclick(INNER_IMG1):
        print('innerauto 중단 - 스크립트 종료')
        os._exit(0)
    time.sleep(1)

    #3. 이미지2 찾고 클릭
    if not _findandclick(INNER_IMG2):
        print('innerauto 중단 - 스크립트 종료')
        os._exit(0)
    time.sleep(1)

    #4. 시스템 종료 (매크로 프로세스만 즉시 종료)
    print('innerauto 완료 - 스크립트 종료')
    os._exit(0)

#=====================================================================
# 실행부 : 전부 메인 스레드에서만 돈다
#=====================================================================

#버프 : F키 한 번
def dobuff(name):
    key = BUFFKEY[name]
    print(name + ' 버프 : ' + key)
    gu.press(key, presses=1)
    time.sleep(BUFF_GAP)

#변신
def dotransform():
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

#귀환 : 여기서 프로세스가 끝난다
def doreturn():
    global ALIVE
    gu.press(KEY_RETURN, presses=1)
    ALIVE = False
    time.sleep(RETURN_WAIT)   #귀환 완료 대기
    innerauto()               #os._exit(0) 로 끝남

#대기 중인 트리거 하나를 꺼내 실행. 실행했으면 True
#사냥 트리거 False -> 해당 트리거 True -> 동작 -> 사냥 트리거 True 복귀
def runpending():
    name = takepending()
    if name == None:
        return False

    settrigger(name)              #사냥 트리거는 여기서 자동으로 False
    if name == 'return':
        doreturn()
    elif name == 'transform':
        dotransform()
    else:
        dobuff(name)
    settrigger('hunt')            #끝나면 사냥 트리거 복구
    return True

#=====================================================================
# 타이머 : request() 와 재등록 외에는 아무것도 하지 않는다
#=====================================================================

def bufftimer(name, interval):
    request(name)
    threading.Timer(interval, bufftimer, args=(name, interval)).start()

#활성 슬롯만 즉시 1회 요청하고 타이머 등록
def startbuffs():
    for name, key, interval in BUFFS:
        if interval > 0:
            request(name)
            threading.Timer(interval, bufftimer, args=(name, interval)).start()
        else:
            print(name + '(' + key + ') 주기 0 - 비활성')

def transformtimer():
    request('transform')
    threading.Timer(TRANSFORM_INTERVAL, transformtimer).start()

#피 확인. 이미지 매칭은 입력을 안 건드리므로 스레드에서 해도 안전
def checkrHp():
    file_path = IMAGE_DIR
    checkrmp = gu.locateCenterOnScreen(file_path + 'checkhp.PNG', confidence=0.8)
    if checkrmp != None:
        print('피 소모 완료 귀환!')
        request('return')
        return                #메인 루프가 처리하고 종료하므로 타이머 재등록 안 함
    threading.Timer(HP_INTERVAL, checkrHp).start()

#=====================================================================
# 사냥 루프 (메인 스레드) - 용던
#=====================================================================
def huntloop(p, atkvalue):
    points  = _scanpoints(p)
    parkpos = (p[0], p[1] + 350)
    cnt     = 0       #클릭 없이 헛돈 횟수

    print('서치 : 8방향 x ' + str(SCAN_ROUND) + '바퀴 (반지름 '
          + str(SCAN_START) + ' 부터 ' + str(SCAN_GAP) + '씩), 총 ' + str(len(points)) + '점')

    settrigger('hunt')
    while ALIVE:
        if runpending():       #버프/변신/귀환이 먼저. 처리했으면 처음부터
            continue

        # sc.run_pending()

        cnt += 1
        if cnt >= NOHIT_LIMIT:         #이 횟수만큼 헛돌면 새로고침
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

if __name__ == '__main__':

    centerpoint = [625, 480]
    #FAILSAFE 대체 : tab 으로 즉시 종료
    k.add_hotkey('tab', lambda: os._exit(0))
    attackinfo = setattckinfo(centerpoint)
    print(attackinfo)

    transformtimer()         #시작 시 변신 1회 요청 + 주기 타이머
    startbuffs()             #활성 버프 슬롯 : 즉시 1회 요청 + 주기 타이머
    checkrHp()               #피 감시

    #기존 스캔박스 위치 유지 (원본 시작점이 y로 40px 위에 잡혔음)
    huntloop([centerpoint[0], centerpoint[1] - 40], attackinfo)
