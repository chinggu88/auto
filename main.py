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
import random
import os.path
import glob
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

#=====================================================================
# 사람처럼 움직이기
#  SetCursorPos 는 중간 좌표 없이 순간이동한다. 사람 손은 그렇게 못 움직인다
#  그래서 '눈에 띄는 이동' 에만 곡선 경로를 그리고, 스캔 프로브는 그대로 순간이동을 쓴다
#  (프로브는 한 바퀴에 32~80번이라 경로를 그리면 사냥 속도가 몇 배로 느려진다)
#=====================================================================
NATURAL_ON   = True    #False 면 예전처럼 전부 순간이동 + 고정 타이밍으로 돌아간다

MOVE_PX_SEC  = 2200.0  #이 속도로 거리에 비례해 이동 시간을 잡는다(px/초)
MOVE_MIN_SEC = 0.05    #아무리 가까워도 이만큼은 쓴다
MOVE_MAX_SEC = 0.30    #아무리 멀어도 이보다는 안 쓴다. 사냥 속도가 죽는다
MOVE_STEP    = 0.010   #중간 좌표를 찍는 간격(초)
MOVE_MIN_PT  = 8       #짧은 이동이라도 최소 이만큼은 나눠 찍는다
                       #시간으로만 나누면 50px 이동이 3점이 돼서 여전히 순간이동처럼 보인다
                       #파이썬 3.11 부터 윈도우 time.sleep 이 고해상도라 6ms 간격도 제대로 쉰다
                       #(3.9 로 돌리면 15.6ms 로 뭉개진다. 그때는 총 이동시간만 맞고 점은 성겨진다)
MOVE_BOW     = 0.15    #경로가 직선에서 벗어나는 정도(거리 대비)
                       #0 이면 직선이라 오히려 티가 난다. 0.3 을 넘기면 손이 떨리는 것처럼 보인다
MOVE_TIME_R  = (0.85, 1.25)   #이동 시간에 곱할 난수 범위. 매번 같은 속도로 가면 티가 난다

CLICK_ADJ    = 7       #클릭 직전 미세 조정 폭(px). 사람은 목표를 한 번에 안 찍고 고쳐 잡는다
CLICK_DELAY  = (0.04, 0.13)   #자리를 잡고 클릭하기까지(초)
SCAN_JITTER  = 5       #스캔점 좌표를 매번 이만큼 흔든다(px)
                       #격자가 완벽하면 사람이 만든 궤적일 수가 없다
                       #덤으로 매 바퀴 조금씩 다른 픽셀을 훑어서 사각지대가 줄어든다
PROBE_JITTER = (1.0, 1.6)     #PROBE_SETTLE 에 곱할 난수 범위. 대기 시간도 일정하면 안 된다

#서치 범위 : 센터포인트 기준 SCAN_DIRS 방향을, 반지름을 1배씩 늘려가며 돈다
SCAN_DIRS  = 16    # 방향 수. 16 이면 22.5도 간격
SCAN_START = 70    # 1배 반지름(px)
SCAN_NEAR  = 2     # 근거리일 때 바퀴 수 -> 반지름 70/140      (32점)
SCAN_FAR   = 5     # 원거리일 때 바퀴 수 -> 반지름 70~350      (80점)
PARK_GAP   = 60    # 가장 바깥 바퀴보다 이만큼 더 아래를 파크 지점으로 잡는다
                   # (파크 지점이 스캔점과 겹치면 커서 초기화가 안 된다)
                   # 거리 설정과 무관하게 항상 SCAN_FAR 기준으로 잡아서 파크 자리를 고정한다
SCAN_OFFSET_Y = -38   # 스캔 중심의 y 보정(px). 음수면 위, 양수면 아래
                      # 원본은 -40 이었고 어택포인트를 2px 내려서 -38

BUFF_GAP    = 1    #버프 키 누른 뒤 대기(초)
LOOP_LIMIT  = 50   #공격 루프 최대 횟수. 채우면 새로고침
                   #칼질을 계속 해도 안 줄고, 새로고침될 때만 초기화된다
HP_INTERVAL = 2    #피/마크 감시 주기(초). 마크 이미지가 늘어서 1초는 빠듯해 2초로 잡음
START_DELAY = 3    #시작 버튼 누르고 게임 창 활성화할 시간(초)

HP_IMG    = 'checkhp.PNG'   #피 부족 경고 UI. 이게 '뜨면' 귀환한다
HP_CONF   = 0.9
MARK_GLOB = 'mark*.PNG'    #적대 혈맹 마크. image 폴더에 있는 걸 전부 긁어온다
MARK_CONF = 0.7            #마크는 배경에 묻혀서 신뢰도를 낮게 잡는다 (구버전 oman.py 값)
                           #파일마다 따로 주고 싶으면 MARK_CONF_BY_FILE 에 적는다
MARK_CONF_BY_FILE = {}     #예) {'mark3.PNG': 0.8} 처럼 파일명만 적으면 그 값이 우선

#=====================================================================
# 소리 감지 : 스피커로 나가는 소리를 루프백으로 받아 '내가 칼질 중'인지만 본다
#  - 칼질 소리가 들리면 이미 몹을 잡고 있는 것이므로 마우스 서치를 멈춘다
#  - 소리가 끊기면 그 자리(스캔점 번호)에서 서치를 이어 돈다
#
# 실측 (KakaoTalk 영상 36~56초 = 칼질이 0.44초 간격으로 반복되는 구간) :
#   칼질중           RMS 약  -6dB,  200Hz 이하가 전체의 18~20%
#   다른 게임 효과음   RMS -13~-25dB, 200Hz 이하가  2~11%
#   무음             RMS 약 -98dB
# 예전 버전은 음량만 봐서 BGM 이나 다른 프로그램 소리에 속았다
# 칼질음은 저음이 유난히 두꺼우므로 음량과 저음 비중을 같이 봐야 갈린다
#=====================================================================
SND_RATE   = 48000     #루프백 장치가 다른 값을 주면 그 값을 쓴다. 여기는 폴백
SND_FRAME  = 1024      #프레임 크기(48kHz 에서 약 21ms)

SND_LOWHZ  = 200.0     #'저음' 의 경계. 이 아래 에너지 비중을 본다
SND_TOPHZ  = 11000.0   #비중을 계산할 때 분모로 쓸 상한
                       #실측은 11kHz 까지만 있는 영상으로 냈다. 분모를 24kHz 까지 벌리면
                       #같은 소리인데도 비중이 낮게 나와서 임계가 안 맞는다

SND_FIGHT_DB  = -9.0   #이 음량을 넘어야 칼질 후보
                       #처음엔 -12 로 뒀는데 몹이 나를 때리는 소리까지 칼질로 잡혔다
                       #몹 공격도 결국 저음이 두꺼운 타격음이라 저음 비중으로는 안 갈린다
                       #실측 : 몹만 나를 때림 -23~-17dB / 내 칼질 -7dB -> 그 사이를 -9 로 잡는다
                       #내 칼질(-7)에 2dB 밖에 여유가 없으니, 칼질을 놓치면 -10~-11 로 내린다
SND_FIGHT_LOW = 15.0   #동시에 저음 비중이 이 %를 넘어야 칼질로 본다
                       #칼질 18~20 / 다른 효과음 2~11 사이라 15 면 양쪽에 여유가 있다
SND_FIGHT_AVG = 0.5    #판정에 쓸 이동평균 창(초)
                       #프레임(21ms) 하나로 재면 타격 스파이크 하나에 놀아난다
SND_FIGHT_ON  = 0.2    #이만큼 연속으로 조건을 만족하면 칼질 시작(초)
SND_FIGHT_OFF = 1.5    #이만큼 연속으로 조건을 못 채워야 칼질 끝(초)
                       #타격 사이 0.44초 공백에 게이트가 덜덜 떨지 않게 시작보다 길게 준다
SND_FIGHT_MAX = 30.0   #칼질중이 이만큼 이어지면 강제 해제(초)
                       #BGM 이나 다른 프로그램 소리가 계속 나면 영영 멈춰 있게 되므로
SND_LOG_SEC   = 5      #측정값 로그 주기(초). 임계를 실기에서 맞출 때 이 값을 보고 조정한다
FIGHT_POLL    = 0.1    #칼질중일 때 사냥 루프가 쉬는 간격(초)

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
#옵션 기본값. 항목이 계속 늘어서 dict 하나로 묶는다 (config.json 에도 이 키 그대로 들어간다)
DEFAULT_OPTS = {
    'attack': True,     #공격(마우스 서치 + 칼질) 사용 여부
    'range':  'near',   #칼 탐지 거리 : 'near'(근거리) / 'far'(원거리)
    'nohit':  2,        #이 횟수만큼 헛돌면 새로고침
    'sound':  False,    #소리로 칼질을 감지해 서치를 멈출지 (추가 패키지가 필요해서 기본 꺼짐)
}
RANGES = [('near', '근거리'), ('far', '원거리')]   #표시 순서

BUFFS   = []      # [(트리거명, 키, 주기(초))]  주기 0 = 비활성
BUFFKEY = {}      # 트리거명 -> 키

KEY_REFRESH        = None   #사냥 헛돌 때 새로고침
KEY_TRANSFORM      = None   #변신
KEY_RETURN         = None   #귀환
TRANSFORM_INTERVAL = 0      #변신 주기(초). 0 이면 변신 안 함
ATTACK_ON          = True   #공격 사용 여부. 끄면 버프/변신/감시만 돈다
SCAN_ROUND         = SCAN_NEAR              #현재 탐지 거리의 바퀴 수
NOHIT_LIMIT        = DEFAULT_OPTS['nohit']  #헛돌 때 새로고침까지의 횟수
SOUND_ON           = DEFAULT_OPTS['sound']  #소리 감지 사용 여부

#=====================================================================
# 트리거 : 한 순간에 하나만 True
#  - TRIGGER 를 바꾸는 것도, 키/마우스를 쓰는 것도 매크로 스레드뿐이다
#  - 타이머 스레드는 PENDING 에 요청만 남기고 물러난다 (마우스 겹침 원천 차단)
#  - GUI 스레드는 입력을 절대 보내지 않는다
#=====================================================================
ALIVE  = False
HOTKEY = None     #tab 핫키 핸들. 정지할 때 떼어낸다

#소리로 판단한 칼질 상태. 소리 스레드가 쓰고 사냥 루프가 읽는다
#bool 하나만 주고받으므로 락은 두지 않는다 (한 박자 늦게 읽어도 다음 프레임에 맞춰진다)
FIGHTING    = False   #True 면 마우스 서치를 멈춘다
FIGHT_READY = False   #소리 감시가 실제로 도는 중인지
                      #루프백을 못 열면 False 라서 게이트가 통째로 꺼지고 예전처럼 계속 서치한다

TRIGGER ={'hunt': False, 'stop': False, 'transform': False, 'return': False}
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

#가감속 곡선(smoothstep) : 시작과 끝은 느리고 가운데가 빠르다
#사람이 마우스를 옮길 때 나오는 속도 모양이다. 등속으로 가면 기계처럼 보인다
def _ease(t):
    return t * t * (3.0 - 2.0 * t)

#2차 베지에 곡선을 따라 이동한다
#  - 제어점을 직선 중간에서 수직으로 밀어 활처럼 휜 경로를 만든다
#  - 휘는 방향과 크기를 매번 난수로 바꾼다. 안 그러면 같은 두 점 사이가 항상 같은 궤적이 된다
#  - 좌표는 가감속 곡선으로, 시간은 등간격으로 나눈다 -> 속도가 자연스럽게 변한다
def _movehuman(x, y):
    try:
        sx, sy = win32api.GetCursorPos()
    except Exception:
        _movefast(x, y)
        return
    ex   = int(x)
    ey   = int(y)
    dx   = ex - sx
    dy   = ey - sy
    dist = math.hypot(dx, dy)
    if dist < 3:                      #이미 거의 제자리면 곡선을 그릴 게 없다
        _movefast(ex, ey)
        return

    dur  = min(MOVE_MAX_SEC, max(MOVE_MIN_SEC, dist / MOVE_PX_SEC))
    dur *= random.uniform(*MOVE_TIME_R)
    bow  = dist * MOVE_BOW * random.uniform(-1.0, 1.0)
    mx   = (sx + ex) * 0.5 - dy / dist * bow
    my   = (sy + ey) * 0.5 + dx / dist * bow

    steps = max(MOVE_MIN_PT, int(dur / MOVE_STEP))
    t0    = time.perf_counter()
    for i in range(1, steps + 1):
        t = _ease(i / float(steps))
        u = 1.0 - t
        win32api.SetCursorPos((int(round(u * u * sx + 2 * u * t * mx + t * t * ex)),
                               int(round(u * u * sy + 2 * u * t * my + t * t * ey))))
        #경과 시간 기준으로 잔다. 루프가 밀려도 전체 이동 시간이 늘어나지 않는다
        gap = (t0 + dur * (i / float(steps))) - time.perf_counter()
        if gap > 0:
            time.sleep(gap)
    _movefast(ex, ey)                 #반올림 오차를 없애고 정확히 목표에 놓는다

#클릭 직전 자리잡기 + 클릭
#미세 조정을 하다가 대상에서 벗어날 수 있으므로, 커서 모양을 다시 보고 어긋났으면 되돌린다
#(원래 좌표는 _probe 가 공격 커서임을 확인한 자리라 확실하다)
def _settleclick(x, y, atkvalue):
    if NATURAL_ON:
        _movehuman(x + random.randint(-CLICK_ADJ, CLICK_ADJ),
                   y + random.randint(-CLICK_ADJ, CLICK_ADJ))
        if win32gui.GetCursorInfo()[1] != atkvalue:
            _movefast(x, y)
            time.sleep(PROBE_STEP)
        time.sleep(random.uniform(*CLICK_DELAY))
    gu.click()

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

#한 바퀴(SCAN_DIRS 방향)를 다 돌고 나서 반지름을 한 배수 늘려 다음 바퀴로 간다
#안쪽부터 바깥으로 : 1배 -> 2배 -> ... -> SCAN_ROUND 배
#모든 방향이 중심에서 같은 거리에 있다 (구버전은 정사각형이라 대각선이 1.4배 멀었음)
def _scanpoints(p):
    pts  = []
    seen = set()
    for i in range(SCAN_ROUND):
        r = SCAN_START * (i + 1)      #1배 70, 2배 140, 3배 210, 4배 280, 5배 350
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

#=====================================================================
# 소리 분석 (DSP) : 오디오 장치와 분리해서 순수 계산만 한다
#  - numpy 는 opencv-python 이 이미 끌고 오므로 추가 설치가 없다
#  - 여기 있는 것들은 장치 없이도 돌아간다 (합성 신호로 검증 가능)
#=====================================================================
try:
    import numpy as _np
    NUMPY_OK = True
except ImportError:
    NUMPY_OK = False

#float 배열 -> dBFS. 무음이면 -120 으로 바닥을 깐다
def _rms_db(buf):
    if len(buf) == 0:
        return -120.0
    r = float(_np.sqrt(_np.mean(_np.square(buf))))
    if r <= 1e-9:
        return -120.0
    return float(20.0 * _np.log10(r))

#int16 바이트 -> 모노 float 배열 (-1.0 ~ 1.0)
def _tomono(raw, channels):
    a = _np.frombuffer(raw, dtype=_np.int16).astype(_np.float32) / 32768.0
    if channels > 1:
        n = (len(a) // channels) * channels
        a = a[:n].reshape(-1, channels).mean(axis=1)
    return a

#저음 비중(%) : SND_TOPHZ 까지의 에너지 중 SND_LOWHZ 아래가 차지하는 비율
#분모를 상한으로 자르는 이유는 SND_TOPHZ 주석에 적어둔 그대로다
#0 번 빈(DC)은 뺀다. 사운드카드에 DC 가 실려 있으면 저음이 부풀려져서 오탐이 된다
def _lowratio(mag, rate):
    n     = len(mag)
    binhz = (rate * 0.5) / max(1, n - 1)
    lo    = max(1, int(SND_LOWHZ / binhz) + 1)
    hi    = min(n, int(SND_TOPHZ / binhz) + 1)
    total = float(_np.sum(mag[1:hi]))
    if total <= 1e-12:
        return 0.0
    return 100.0 * float(_np.sum(mag[1:lo])) / total

#한 프레임의 (음량, 저음비중) 을 받아 칼질중인지 판정한다
#판정을 이 클래스에 몰아두면 장치 없이도 값만 밀어 넣어 확인할 수 있다
#  - 시작은 짧게(ON), 끝은 길게(OFF) 잡는 히스테리시스
#    타격 사이 0.44초 공백에 게이트가 덜덜 떨면 서치가 들락날락해서 오히려 손해다
#  - MAX 를 넘기면 강제로 풀고, 한 번 조용해지기 전까지 다시 안 들어간다
#    BGM 을 켜 뒀을 때 영영 멈춰 있는 것을 막는 안전장치다
class FightGate:
    def __init__(self, framesec, db=None, low=None, avg=None,
                 on=None, off=None, maxsec=None):
        self.framesec = framesec
        self.db       = SND_FIGHT_DB  if db     == None else db
        self.low      = SND_FIGHT_LOW if low    == None else low
        self.on       = SND_FIGHT_ON  if on     == None else on
        self.off      = SND_FIGHT_OFF if off    == None else off
        self.maxsec   = SND_FIGHT_MAX if maxsec == None else maxsec
        self.win      = max(1, int((SND_FIGHT_AVG if avg == None else avg) / framesec))
        self.dbbuf    = []
        self.lowbuf   = []
        self.fight    = False
        self.forced   = False    #MAX 초과로 강제 해제된 상태인가
        self.hotsec   = 0.0      #연속으로 조건을 만족한 시간
        self.coldsec  = 0.0      #연속으로 조건을 못 채운 시간
        self.fightsec = 0.0      #칼질중으로 본 지 얼마나 됐나
        self.avgdb    = -120.0   #마지막 이동평균 (로그용)
        self.avglow   = 0.0
        self.event    = None     #이번 프레임에 상태가 바뀌었으면 'on'/'off'/'forced'

    def push(self, db, low):
        self.event = None
        self.dbbuf.append(db)
        self.lowbuf.append(low)
        if len(self.dbbuf) > self.win:
            self.dbbuf.pop(0)
            self.lowbuf.pop(0)
        self.avgdb  = sum(self.dbbuf)  / len(self.dbbuf)
        self.avglow = sum(self.lowbuf) / len(self.lowbuf)

        #음량과 저음 비중을 둘 다 넘겨야 칼질로 본다
        if self.avgdb > self.db and self.avglow > self.low:
            self.hotsec += self.framesec
            self.coldsec = 0.0
        else:
            self.coldsec += self.framesec
            self.hotsec   = 0.0

        if not self.fight:
            if self.forced:
                if self.coldsec >= self.off:
                    self.forced = False
            elif self.hotsec >= self.on:
                self.fight    = True
                self.fightsec = 0.0
                self.event    = 'on'
        else:
            self.fightsec += self.framesec
            if self.coldsec >= self.off:
                self.fight = False
                self.event = 'off'
            elif self.fightsec >= self.maxsec:
                self.fight  = False
                self.forced = True
                self.event  = 'forced'
        return self.fight

#image 폴더에 들어있는 마크 이미지를 전부 긁어온다
#  - 파일만 넣어두면 코드 수정 없이 감시 대상에 추가된다 (mark5.PNG 등)
#  - 파일명 순으로 정렬해서 mark1, mark2 ... 순서로 본다
#  - 한 번 읽고 캐시한다. 사냥 중에 폴더를 뒤지지 않기 위함
MARK_FILES = None
def markfiles():
    global MARK_FILES
    if MARK_FILES != None:
        return MARK_FILES

    found = glob.glob(IMAGE_DIR + MARK_GLOB) + glob.glob(IMAGE_DIR + 'mark*.png')
    #윈도우 glob 은 대소문자를 안 가려서 같은 파일이 두 번 잡힌다. 파일명 기준으로 중복 제거
    seen  = {}
    for path in found:
        seen[os.path.basename(path).lower()] = path
    MARK_FILES = [seen[name] for name in sorted(seen.keys())]

    if len(MARK_FILES) == 0:
        log('마크 이미지 없음 : ' + IMAGE_DIR + MARK_GLOB + ' 에 파일이 하나도 없다')
    else:
        log('마크 이미지 ' + str(len(MARK_FILES)) + '개 : ' + ', '.join([os.path.basename(x) for x in MARK_FILES]))
    return MARK_FILES

#피 확인. 이미지 매칭은 입력을 안 건드리므로 스레드에서 해도 안전
def checkrHp():
    if not ALIVE:
        return
    file_path = IMAGE_DIR

    #1. 피 부족 경고 UI 가 '뜨면' 귀환
    if gu.locateCenterOnScreen(file_path + HP_IMG, confidence=HP_CONF) != None:
        log('피 소모 완료 귀환!')
        request('return')
        return                #매크로 루프가 처리하고 종료하므로 타이머 재등록 안 함

    #2. 적대 혈맹 마크. image 폴더에 있는 mark*.PNG 를 전부 돌린다
    #   하나라도 걸리면 나머지는 볼 필요가 없으므로 바로 귀환
    for markpath in markfiles():
        markname = os.path.basename(markpath)
        markconf = MARK_CONF_BY_FILE.get(markname, MARK_CONF)
        if gu.locateCenterOnScreen(markpath, confidence=markconf) != None:
            log('적대 마크 발견 (' + markname + ') 귀환!')
            request('return')
            return

    _arm(HP_INTERVAL, checkrHp)

#=====================================================================
# 소리 감시 스레드
#  - 키/마우스를 절대 안 건드린다. 숫자를 뽑아 FIGHTING 만 세운다
#  - ALIVE 를 보고 스스로 끝난다. dostop() 은 손댈 필요 없다
#  - 패키지가 없거나 장치를 못 열면 경고만 찍고 조용히 빠진다 (사냥은 계속 돈다)
#=====================================================================

#기본 스피커의 루프백 입력 장치를 찾는다. 못 찾으면 (None, 사유)
def _findloopback(pa):
    try:
        return pa.get_default_wasapi_loopback(), None
    except Exception:
        pass
    #구버전 PyAudioWPatch 폴백 : 루프백 장치를 직접 훑는다
    try:
        for dev in pa.get_loopback_device_info_generator():
            return dev, None
    except Exception as e:
        return None, str(e)
    return None, '루프백 장치를 못 찾음'

def soundwatch():
    global FIGHTING, FIGHT_READY
    if not NUMPY_OK:
        log('소리 : numpy 가 없어서 끕니다')
        return
    try:
        import pyaudiowpatch as pa
    except ImportError:
        log('소리 : PyAudioWPatch 가 없어서 끕니다  (pip install PyAudioWPatch)')
        return

    p = st = None
    try:
        p        = pa.PyAudio()
        dev, err = _findloopback(p)
        if dev == None:
            log('소리 : 루프백 장치를 못 엽니다 - ' + str(err))
            return

        rate = int(dev.get('defaultSampleRate', SND_RATE))
        ch   = int(dev.get('maxInputChannels', 2)) or 2
        st   = p.open(format=pa.paInt16, channels=ch, rate=rate, input=True,
                      input_device_index=dev['index'], frames_per_buffer=SND_FRAME)
        log('소리 : 루프백 = ' + str(dev.get('name')) + '  ' + str(rate) + 'Hz  ' + str(ch) + 'ch')
        log('소리 : 칼질 판정 = %.0fdB 초과 이면서 저음 %.0f%% 초과가 %.1fs 이어지면 시작, '
            '%.1fs 못 채우면 끝' % (SND_FIGHT_DB, SND_FIGHT_LOW, SND_FIGHT_ON, SND_FIGHT_OFF))

        framesec = float(SND_FRAME) / rate
        gate     = FightGate(framesec)
        window   = _np.hanning(SND_FRAME)
        nextlog  = time.time() + SND_LOG_SEC
        peakdb   = -120.0     #로그 주기 동안의 최대값. 임계를 맞출 때 이게 제일 쓸모 있다
        peaklow  = 0.0
        fightsec = 0.0        #로그 주기 동안 칼질로 본 시간

        FIGHT_READY = True      #여기서부터 사냥 루프가 FIGHTING 을 믿는다

        while ALIVE:
            raw = st.read(SND_FRAME, exception_on_overflow=False)
            buf = _tomono(raw, ch)
            if len(buf) != len(window):
                window = _np.hanning(len(buf))
            mag = _np.abs(_np.fft.rfft(buf * window))
            db  = _rms_db(buf)
            low = _lowratio(mag, rate)

            FIGHTING = gate.push(db, low)

            if gate.event == 'on':
                log('소리 : 칼질 감지 (%.1fdB / 저음 %.0f%%) - 서치 멈춤' % (gate.avgdb, gate.avglow))
            elif gate.event == 'off':
                log('소리 : 칼질 끝 (%.1fs) - 멈춘 자리에서 서치 재개' % gate.fightsec)
            elif gate.event == 'forced':
                log('소리 : 칼질 %.0fs 초과 - 강제 해제하고 서치 재개 (BGM 확인)' % gate.fightsec)

            if db > peakdb:
                peakdb = db
            if low > peaklow:
                peaklow = low
            if gate.fight:
                fightsec += framesec

            #임계를 실기에서 맞추라고 주기적으로 실측값을 찍는다
            #칼질할 때 최대 dB / 저음% 를 보고 SND_FIGHT_DB, SND_FIGHT_LOW 를 조정하면 된다
            now = time.time()
            if now >= nextlog:
                log('소리 : 최근 %ds  최대 %.1fdB  최대 저음 %.0f%%  칼질 %.1fs'
                    % (SND_LOG_SEC, peakdb, peaklow, fightsec))
                peakdb   = -120.0
                peaklow  = 0.0
                fightsec = 0.0
                nextlog  = now + SND_LOG_SEC

    except Exception as e:
        log('소리 감시 오류 : ' + str(e))
    finally:
        try:
            if st != None:
                st.stop_stream()
                st.close()
        except Exception:
            pass
        try:
            if p != None:
                p.terminate()
        except Exception:
            pass
        FIGHT_READY = False
        FIGHTING    = False      #소리가 죽어도 사냥 루프가 멈춰 있으면 안 된다
        log('소리 감시 종료')

#=====================================================================
# 사냥 루프 (매크로 스레드) - 용던
#=====================================================================
def huntloop(p, atkvalue):
    points  = _scanpoints(p)
    #파크는 가장 바깥 바퀴보다 더 아래. 안 그러면 5배 바퀴의 6시 점과 겹친다
    #근거리로 좁혀도 파크 자리는 안 움직이게 SCAN_FAR 기준으로 고정한다
    parkpos = (p[0], p[1] + SCAN_START * SCAN_FAR + PARK_GAP)
    cnt     = 0       #클릭 없이 헛돈 횟수 (칼질하면 초기화)
    loopcnt = 0       #공격 루프 누적 횟수 (새로고침될 때만 초기화)
    idx     = 0       #지금 볼 스캔점 번호. 전투로 멈췄다 이어 돌려고 while 밖에 둔다

    if ATTACK_ON:
        radii = ','.join(str(SCAN_START * (i + 1)) for i in range(SCAN_ROUND))
        log('서치 : ' + ('근거리' if SCAN_ROUND <= SCAN_NEAR else '원거리')
            + '  ' + str(SCAN_DIRS) + '방향 x ' + str(SCAN_ROUND) + '바퀴'
            + '  반지름 ' + radii + '  총 ' + str(len(points)) + '점')
        log('파크 : ' + str(parkpos[0]) + ',' + str(parkpos[1]))

    settrigger('hunt')
    while ALIVE:
        if runpending():       #버프/변신/귀환이 먼저. 처리했으면 처음부터
            continue

        #공격 꺼짐 : 마우스를 아예 안 건드리고 버프/변신/감시만 돌린다
        if not ATTACK_ON:
            time.sleep(0.2)    #풀스핀 방지
            continue

        #칼질 소리가 들리면 이미 몹을 잡고 있는 것이므로 커서를 아예 안 건드린다
        #idx 를 그대로 두므로 소리가 끊기면 멈춘 자리(중간)에서 이어서 돈다
        if FIGHT_READY and FIGHTING:
            time.sleep(FIGHT_POLL)
            continue

        # sc.run_pending()

        x, y = points[idx]
        idx += 1

        if idx >= len(points):    #한 바퀴를 다 돌았다
            idx      = 0
            cnt     += 1
            loopcnt += 1
            #헛돌았거나(cnt) 루프를 최대 횟수만큼 돌았으면(loopcnt) 새로고침
            if KEY_REFRESH != None and (cnt >= NOHIT_LIMIT or loopcnt >= LOOP_LIMIT):
                log('새로고침 : ' + KEY_REFRESH
                    + '  (헛돔 ' + str(cnt) + '/' + str(NOHIT_LIMIT)
                    + ', 누적 ' + str(loopcnt) + '/' + str(LOOP_LIMIT) + ')')
                gu.press(KEY_REFRESH, presses=1)
                cnt     = 0
                loopcnt = 0       #누적 횟수는 여기서만 초기화된다

        #격자를 그대로 찍지 않고 매번 조금씩 흔든다 (무비용)
        if NATURAL_ON:
            x += random.randint(-SCAN_JITTER, SCAN_JITTER)
            y += random.randint(-SCAN_JITTER, SCAN_JITTER)

        _movefast(parkpos[0], parkpos[1])   #커서 초기화 (park)
        time.sleep(PROBE_SETTLE * random.uniform(*PROBE_JITTER) if NATURAL_ON else PROBE_SETTLE)
        if _probe(x, y, atkvalue):
            #ctrl 강제공격은 뺐다. 그냥 클릭만 한다
            # gu.keyDown('ctrl')
            # time.sleep(CTRL_DELAY)
            _settleclick(x, y, atkvalue)
            # gu.keyUp('ctrl')
            cnt = 0
            if not FIGHT_READY:
                idx = 0         #소리 감시가 없으면 예전처럼 1바퀴 첫 방향부터 다시 스캔
                                #(소리가 있으면 곧 칼질로 멈추고, 끝난 뒤 다음 점부터 이어 돈다)

#=====================================================================
# 설정 저장 / 불러오기 (exe 옆 config.json)
#=====================================================================

#파일에서 읽어 (seconds, roles, opts) 로 돌려준다. 없거나 깨졌으면 기본값
def loadconfig(path=None):
    if path == None:
        path = CONFIG_PATH
    seconds = dict(DEFAULT_SECONDS)
    roles   = dict(DEFAULT_ROLES)
    opts    = dict(DEFAULT_OPTS)
    if not os.path.isfile(path):
        return seconds, roles, opts, False

    try:
        f = open(path, 'r', encoding='utf-8')
        data = json.load(f)
        f.close()
    except Exception as e:
        log('설정 불러오기 실패, 기본값 사용 : ' + str(e))
        return seconds, roles, opts, False

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

    #옵션은 아는 키만, 값이 이상하면 기본값을 유지한다
    if isinstance(data.get('attack'), bool):
        opts['attack'] = data['attack']
    if isinstance(data.get('sound'), bool):
        opts['sound'] = data['sound']
    if data.get('range') in [r for r, label in RANGES]:
        opts['range'] = data['range']
    try:
        v = int(data.get('nohit', opts['nohit']))
        if v >= 1:
            opts['nohit'] = v
    except (TypeError, ValueError):
        pass
    return seconds, roles, opts, True

def saveconfig(seconds, roles, opts, path=None):
    if path == None:
        path = CONFIG_PATH
    data = {'seconds': dict((key, int(seconds.get(key, 0))) for key in FKEYS),
            'roles':   dict((rid, roles.get(rid)) for rid in ('return', 'refresh', 'transform')),
            'attack':  bool(opts.get('attack', DEFAULT_OPTS['attack'])),
            'range':   str(opts.get('range',  DEFAULT_OPTS['range'])),
            'nohit':   int(opts.get('nohit',  DEFAULT_OPTS['nohit'])),
            'sound':   bool(opts.get('sound',  DEFAULT_OPTS['sound']))}
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
def applyconfig(seconds, roles, opts=None):
    #seconds : {키 -> 초},  roles : {'return'/'refresh'/'transform' -> 키 or None}
    #opts    : {'attack': bool, 'range': 'near'/'far', 'nohit': int, 'sound': bool}
    global BUFFS, BUFFKEY, TRIGGER, ORDER, PENDING
    global KEY_RETURN, KEY_REFRESH, KEY_TRANSFORM, TRANSFORM_INTERVAL
    global ATTACK_ON, SCAN_ROUND, NOHIT_LIMIT, SOUND_ON

    if opts == None:
        opts = dict(DEFAULT_OPTS)
    ATTACK_ON     = bool(opts.get('attack', DEFAULT_OPTS['attack']))
    SCAN_ROUND    = SCAN_FAR if opts.get('range') == 'far' else SCAN_NEAR
    NOHIT_LIMIT   = max(1, int(opts.get('nohit', DEFAULT_OPTS['nohit'])))
    SOUND_ON      = bool(opts.get('sound', DEFAULT_OPTS['sound']))
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

        #공격을 끄면 커서 캘리브레이션(이동+클릭)도 할 필요가 없다
        atk = None
        if ATTACK_ON:
            atk = setattckinfo(CENTERPOINT)
            log('공격 커서 : ' + str(atk))
        else:
            log('공격 끔 - 버프/변신/감시만 돕니다')

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

        #소리 감시는 입력을 안 건드리므로 별도 스레드로 띄운다. ALIVE 보고 스스로 끝난다
        if SOUND_ON:
            t = threading.Thread(target=soundwatch)
            t.daemon = True
            t.start()
        else:
            log('소리 감지 끔 - 서치를 계속 돕니다')

        huntloop([CENTERPOINT[0], CENTERPOINT[1] + SCAN_OFFSET_Y], atk)
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

        #--- 동작 설정 ---
        optbox = ttk.LabelFrame(root, text='동작')
        optbox.pack(fill='x', padx=10, pady=(8, 0))
        self.attack = tk.BooleanVar(value=DEFAULT_OPTS['attack'])
        self.atkchk = ttk.Checkbutton(optbox, text='공격 사용 (마우스 서치 + 칼질)',
                                      variable=self.attack)
        self.atkchk.pack(anchor='w', padx=6, pady=4)
        ttk.Label(optbox, foreground='#555',
                  text='끄면 마우스를 아예 안 건드리고 버프 / 변신 / 피·마크 감시만 돕니다.'
                  ).pack(anchor='w', padx=6, pady=(0, 4))

        #--- 칼 탐지 거리 ---
        rngrow = ttk.Frame(optbox)
        rngrow.pack(fill='x', padx=6, pady=(6, 0))
        ttk.Label(rngrow, text='칼 탐지 거리', width=12).pack(side='left')
        self.range  = tk.StringVar(value=DEFAULT_OPTS['range'])
        self.rngbtn = []
        for rid, label in RANGES:
            n  = SCAN_FAR if rid == 'far' else SCAN_NEAR
            rb = ttk.Radiobutton(rngrow,
                                 text='%s (%d~%dpx, %d점)'
                                      % (label, SCAN_START, SCAN_START * n, SCAN_DIRS * n),
                                 value=rid, variable=self.range)
            rb.pack(side='left', padx=(0, 12))
            self.rngbtn.append(rb)

        #--- 새로고침 트리거 ---
        nhrow = ttk.Frame(optbox)
        nhrow.pack(fill='x', padx=6, pady=(4, 6))
        ttk.Label(nhrow, text='새로고침 트리거', width=12).pack(side='left')
        self.nohit = tk.StringVar(value=str(DEFAULT_OPTS['nohit']))
        self.nhent = ttk.Entry(nhrow, textvariable=self.nohit, width=6, justify='center')
        self.nhent.pack(side='left')
        ttk.Label(nhrow, foreground='#555',
                  text='  회 연속 헛돌면 새로고침 키를 누릅니다 (한 번이라도 잡으면 초기화)'
                  ).pack(side='left')

        #--- 소리 감지 ---
        self.sound  = tk.BooleanVar(value=DEFAULT_OPTS['sound'])
        self.sndchk = ttk.Checkbutton(optbox, text='소리로 칼질 감지 (칼질중이면 서치 멈춤)',
                                      variable=self.sound)
        self.sndchk.pack(anchor='w', padx=6, pady=(6, 0))
        ttk.Label(optbox, foreground='#555',
                  text='스피커로 나가는 소리를 듣고 칼질중이면 마우스 서치를 멈췄다가, '
                       '소리가 끊기면 멈춘 자리에서 이어서 돕니다.\n'
                       'PyAudioWPatch 가 필요하고, 게임 BGM 을 끄면 판정이 정확해집니다. '
                       '장치를 못 열면 자동으로 꺼지고 예전처럼 계속 서치합니다.'
                  ).pack(anchor='w', padx=6, pady=(0, 4))

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
        seconds, roles, opts, found = loadconfig()
        self.setform(seconds, roles, opts)
        self.drainlog()
        log(('설정 불러옴 : ' + CONFIG_PATH) if found else '저장된 설정 없음 - 기본 셋팅 사용')

    #--- 폼 <-> 값 ---

    #값을 위젯에 넣는다
    def setform(self, seconds, roles, opts):
        for key in FKEYS:
            self.sec[key].set(str(seconds.get(key, 0)))
            for rid, label in ROLES:
                self.role[(key, rid)].set(roles.get(rid) == key)
        self.attack.set(bool(opts.get('attack', DEFAULT_OPTS['attack'])))
        self.range.set(str(opts.get('range',  DEFAULT_OPTS['range'])))
        self.nohit.set(str(opts.get('nohit',  DEFAULT_OPTS['nohit'])))
        self.sound.set(bool(opts.get('sound',  DEFAULT_OPTS['sound'])))
        self.refreshrows()

    #위젯에서 값을 읽는다. 주기가 숫자가 아니면 (None, None, None) 을 돌려준다
    def readform(self):
        seconds = {}
        for key in FKEYS:
            raw = self.sec[key].get().strip()
            if raw == '':
                raw = '0'
            if not raw.isdigit():
                log('주기는 0 이상 정수만 : ' + key.upper() + ' = ' + raw)
                return None, None, None
            seconds[key] = int(raw)

        raw = self.nohit.get().strip()
        if not raw.isdigit() or int(raw) < 1:
            log('새로고침 트리거는 1 이상 정수만 : ' + raw)
            return None, None, None

        roles = {}
        for rid, label in ROLES:
            roles[rid] = None
            for key in FKEYS:
                if self.role[(key, rid)].get():
                    roles[rid] = key
                    break
        opts = {'attack': self.attack.get(),
                'range':  self.range.get(),
                'nohit':  int(raw),
                'sound':  self.sound.get()}
        return seconds, roles, opts

    def onsave(self):
        seconds, roles, opts = self.readform()
        if seconds == None:
            return
        if saveconfig(seconds, roles, opts):
            log('설정 저장 : ' + CONFIG_PATH)

    def onload(self):
        seconds, roles, opts, found = loadconfig()
        self.setform(seconds, roles, opts)
        log(('설정 불러옴 : ' + CONFIG_PATH) if found
            else '저장된 설정 파일 없음 - 기본 셋팅으로 되돌림')

    def ondefault(self):
        self.setform(dict(DEFAULT_SECONDS), dict(DEFAULT_ROLES), dict(DEFAULT_OPTS))
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
        for b in (self.savebtn, self.loadbtn, self.defbtn, self.atkchk, self.nhent) + tuple(self.rngbtn):
            b.configure(state='disabled')
        self.btn.configure(state='disabled', text='동작 중  (tab = 정지)')

    #정지하면 설정을 다시 만질 수 있게 열어준다
    def unlockui(self):
        for key in FKEYS:
            for rid, label in ROLES:
                self.check[(key, rid)].configure(state='normal')
        for b in (self.savebtn, self.loadbtn, self.defbtn, self.atkchk, self.nhent) + tuple(self.rngbtn):
            b.configure(state='normal')
        self.btn.configure(state='normal', text='시작하기')
        self.refreshrows()      #주기 입력칸은 역할에 따라 다시 결정
        self.started = False
        self.thread  = None

    def onstart(self):
        if self.started:
            return

        seconds, roles, opts = self.readform()
        if seconds == None:
            log('시작 실패 - 주기 값을 확인하세요')
            return

        saveconfig(seconds, roles, opts)   #시작할 때 쓴 설정을 그대로 저장해둔다
        applyconfig(seconds, roles, opts)

        log('=== 설정 ===')
        log('  공격 : ' + ('사용' if opts['attack'] else '끔'))
        log('  칼 탐지 거리 : ' + dict(RANGES)[opts['range']]
            + ' (반지름 ' + str(SCAN_START) + '~' + str(SCAN_START * SCAN_ROUND) + 'px)')
        log('  새로고침 트리거 : ' + str(opts['nohit']) + '회 헛돌면')
        log('  소리 감지 : ' + ('사용' if opts.get('sound') else '끔'))
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
