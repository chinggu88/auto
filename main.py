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
import traceback

#마크 매칭에 쓴다. 없으면 예전 방식(pyautogui)으로 조용히 물러난다
try:
    import numpy
    import cv2
    MASK_OK = True
except Exception:
    MASK_OK = False
import sys
import tkinter as tk
import memread as mr     #엔티티 테이블 읽기 (읽기 전용). 사냥 대상과 주변 캐릭터를 여기서 얻는다
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
CENTERPOINT = [720, 540]

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

CLICK_ADJ    = 8       #클릭 직전 미세 조정 폭(px). 사람은 목표를 한 번에 안 찍고 고쳐 잡는다
CLICK_DELAY  = (0.04, 0.13)   #자리를 잡고 클릭하기까지(초)
SCAN_JITTER  = 6       #스캔점 좌표를 매번 이만큼 흔든다(px)
                       #격자가 완벽하면 사람이 만든 궤적일 수가 없다
                       #덤으로 매 바퀴 조금씩 다른 픽셀을 훑어서 사각지대가 줄어든다
PROBE_JITTER = (1.0, 1.6)     #PROBE_SETTLE 에 곱할 난수 범위. 대기 시간도 일정하면 안 된다

#서치 범위 : 센터포인트 기준 SCAN_DIRS 방향을, 반지름을 1배씩 늘려가며 돈다
SCAN_DIRS  = 16    # 방향 수. 16 이면 22.5도 간격
SCAN_START = 79    # 1배 반지름(px)
SCAN_NEAR  = 2     # 근거리일 때 바퀴 수 -> 반지름 70/140      (32점)
SCAN_FAR   = 5     # 원거리일 때 바퀴 수 -> 반지름 70~350      (80점)
PARK_GAP   = 68    # 가장 바깥 바퀴보다 이만큼 더 아래를 파크 지점으로 잡는다
                   # (파크 지점이 스캔점과 겹치면 커서 초기화가 안 된다)
                   # 거리 설정과 무관하게 항상 SCAN_FAR 기준으로 잡아서 파크 자리를 고정한다
SCAN_OFFSET_Y = -43   # 스캔 중심의 y 보정(px). 음수면 위, 양수면 아래
                      # 원본은 -40 이었고 어택포인트를 2px 내려서 -38

BUFF_GAP    = 1    #채팅버프를 보낸 뒤 대기(초)
BUFF_KEY_GAP = 0.2 #버프 키 하나를 누른 뒤 다음 버프 키까지 대기(초). 버프는 한 번에 하나씩 이 간격으로 누른다
#단축키 페이지 : 게임의 F5~F12 단축키 칸은 F1 / F2 로 페이지를 바꾼다
#  F1 = 공격 페이지 (공격 탭의 공격 키 / 새로고침 / 힐 / 이뮨 / 베르)
#  F2 = 버프 페이지 (버프 탭의 버프 / 변신)
#사냥은 F1 페이지에서 하고, 버프를 누를 때만 F2 로 갔다가 F1 로 돌아온다. 시작할 때도 같다
PAGE_ATTACK = 'f1'
PAGE_BUFF   = 'f2'
PAGE_GAP    = 0.3  #페이지 키를 누른 뒤 단축키 칸이 바뀔 때까지 대기(초)
TRANSFORM_WAIT     = 1.0   #변신 키를 누르기 전 대기(초). 바로 앞 버프의 시전이 끝나야 변신 키가 먹는다
TRANSFORM_MENU_SEC = 3.0   #변신 메뉴(lv80.PNG)가 뜰 때까지 기다리는 최대 시간(초)
TRANSFORM_MENU_POLL = 0.3  #그동안 메뉴를 다시 찾는 간격(초)
CHAT_CMD      = '.버프'   #채팅창에 넣는 매크로 명령어
CHAT_INTERVAL = 900       #채팅버프 주기(초). 15분
CHAT_GAP      = 0.3       #엔터 -> 입력 -> 엔터 사이 대기(초)
LOOP_LIMIT  = 50   #공격 루프 최대 횟수. 채우면 새로고침
                   #칼질을 계속 해도 안 줄고, 새로고침될 때만 초기화된다
HP_INTERVAL = 2    #피/마크 감시 주기(초). 마크 이미지가 늘어서 1초는 빠듯해 2초로 잡음
START_DELAY = 3    #시작 버튼 누르고 게임 창 활성화할 시간(초)

HP_IMG    = 'checkhp.PNG'   #피 부족 경고 UI. 이게 '뜨면' 귀환한다
HP_CONF   = 0.9
MARK_GLOB = 'mark*.PNG'    #적대 혈맹 마크. png(화면 캡처)와 bmp(혈맹문장 원본)를 긁어온다
                           #같은 번호가 둘 다 있으면 bmp(원본)를 우선한다
                           #bmp 는 검정이 게임에서 투명으로 렌더링되므로 마스크 매칭(1번 방법)을 쓴다
MARK_CONF = 0.85            #마크 신뢰도. 진짜 마크를 놓치면 더 내려볼 것
                           #파일마다 따로 주고 싶으면 MARK_CONF_BY_FILE 에 적는다
MARK_CONF_BY_FILE = {}     #예) {'mark3.bmp': 0.8} 처럼 파일명만 적으면 그 값이 우선
MARK_BG_TOL = 25           #검정 배경을 투명으로 보고 매칭에서 뺄 때의 기준값 (1번 방법)
                           #bmp 원본에만 적용한다. png 화면 캡처는 배경이 진짜라 마스크를 안 쓴다
MARK_SCALES = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
                           #bmp 원본 크기 대비 탐색 배율. 화면의 실제 마크 크기를 몰라도 된다
                           #템플릿 매칭은 스케일 불변성이 없어서 크기가 안 맞으면 점수가 안 나온다.
                           #여러 배율로 돌려 가장 잘 맞는 것을 고르면 측정 없이도 된다
MARK_MAX  = 4              #mark1 ~ mark(이 번호) 까지만 본다. 0 이면 폴더에 있는 걸 전부
                           #번호가 없거나 범위를 넘는 파일(mark4.bmp 등)은 폴더에 있어도 건너뛴다

#내 마크는 적이 아니므로 무시한다
#  - 캐릭터는 항상 화면 중앙(CENTERPOINT)에 있다. 아래 자리들은 CENTERPOINT 기준 보정값(px)
#  - 실측 : 내 마크가 (625, 852) 에 잡힘 -> 중앙에서 아래로 372
#  - 구버전 turn.py 가 mark4 를 x 600~650, y 346 에서 걸러낸 흔적도 있어 위쪽 134 도 같이 둠
#    (실기에서 안 잡히는 자리면 지워도 된다)
#  - 자리마다 MARK_SELF_RADIUS 안에 들어온 매칭은 버린다. 귀환 로그의 좌표 보고 맞출 것
MARK_SELF_OFFSETS = [
    [0,  419],   #(720, 959) 실측
    [0, -151],   #(720, 389) 머리 위. turn.py 값
]
MARK_SELF_RADIUS = 90          #이 거리(px) 안이면 내 마크로 본다. 0 이면 예외처리 끔
MARK_BOTTOM_CUT = 0.88         #화면 높이의 이 비율 아래쪽은 마크 탐지 제외 (하단 HP바/채팅 UI 오탐 방지). 1.0 이면 끔

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

#초 -> '1시간 23분 45초'. 사냥 시간 로그용
def fmtsec(sec):
    sec = int(sec)
    h = sec // 3600
    m = (sec % 3600) // 60
    ss = sec % 60
    if h > 0:
        return str(h) + '시간 ' + str(m) + '분 ' + str(ss) + '초'
    if m > 0:
        return str(m) + '분 ' + str(ss) + '초'
    return str(ss) + '초'

#=====================================================================
# 런타임 설정 : GUI 가 시작 전에 채운다
#=====================================================================
FKEYS = ['f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12']

#기본 셋팅 : config.json 이 없을 때 이 값으로 시작한다
DEFAULT_SECONDS = {
    'f5':     0,   #새로고침 - 주기 없음
    'f6':  4,
    'f7':  1800,
    'f8':     0,
    'f9':     5,
    'f10':  1830,
    'f11': 1800,   #변신 주기
    'f12':    1800,   #귀환 - 주기 없음
}
DEFAULT_ROLES = {
    'refresh':   'f5',
    'transform': 'f7',    #변신 - 버프 페이지(F2) 의 키. 버프 탭에서 고른다
    'heal':      None,    #힐 - HP 가 정한 % 이하로 내려가면 누른다
    'immune':    None,    #이뮨 - 주위 몹이 정한 수 이상이면 누른다
    'ber':       None,    #베르 - 힐과 같은 방식 (HP % 는 따로 정한다)
}
ROLE_IDS = ['refresh', 'transform', 'heal', 'immune', 'ber']   #config.json 에 저장하는 역할 목록
#(예전의 'skill' 역할은 공격 탭으로 옮겼다. 옛 config.json 의 roles.skill 은 불러올 때 공격 키 1번으로 바꾼다.
# 'return'(귀환) 역할은 뺐다. KEY_RETURN 은 항상 None 이고 피 / 주변 캐릭터 감시는 감지만 모드에서만 돈다)
PAGE_ROLES = ['refresh', 'heal', 'immune', 'ber']   #공격 페이지(F1) 의 역할. 공격 키와 겹치면 안 된다

#공격 키 : 대상을 클릭한 뒤 조건이 맞으면 누르는 키. 공격 탭에서 최대 ATTACK_MAX 개까지 둔다
#  key   : f5~f12 또는 None (안 씀)
#  delay : 다시 누르기까지의 간격(초)
#  dist  : 대상과의 거리(타일)가 이 값 이하일 때만 누른다
#버프 / 변신 / 귀환 / 채팅버프(runpending) 가 먼저 처리되고 나서야 공격 키 차례가 온다
ATTACK_MAX  = 4
DIST_CHOICES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]     #공격 키의 몹과의 거리 드롭다운
def defaultattacks():
    #기본 한 개 : F6, 4초, 거리 3 (예전 공격스킬 기본값과 같다). 매번 새 리스트를 만든다
    return [{'key': 'f6', 'delay': 4.0, 'dist': 3}]
#옵션 기본값. 항목이 계속 늘어서 dict 하나로 묶는다 (config.json 에도 이 키 그대로 들어간다)
DEFAULT_OPTS = {
    'attack': True,     #공격(마우스 서치 + 칼질) 사용 여부
    'range':  'near',   #칼 탐지 거리 : 'near'(근거리) / 'far'(원거리)
    'nohit':  2,        #이 횟수만큼 헛돌면 새로고침
    'sound':  False,    #소리로 칼질을 감지해 서치를 멈출지 (추가 패키지가 필요해서 기본 꺼짐)
    'dist':   8,        #사냥 탐지 거리(타일). 이 안의 몹만 대상으로 삼는다
    'detect': False,    #감지만 : 몹/캐릭터를 로그에만 찍고 클릭도 귀환도 안 한다 (확인용)
    'heal_pct': 50,     #HP 가 이 % 이하면 힐 키
    'ber_pct':  50,     #HP 가 이 % 이하면 베르 키
    'immune_n': 4,      #주위 몹이 이 수 이상이면 이뮨 키
    'attacks':  None,   #공격 키 목록 [{'key','delay','dist'}, ...]. None 이면 defaultattacks()
    'gaps':     None,   #힐 / 베르 / 이뮨 재사용 간격(초) {'heal','ber','immune'}. 0 = GAP_DEFAULT. None 이면 전부 0
                        #(버프 탭의 주기 칸과 별개다. F1 페이지의 역할 키와 F2 페이지의 버프가 같은 F 키일 수 있다)
}
def defaultgaps():
    return {'heal': 0, 'ber': 0, 'immune': 0}
PCT_CHOICES = [10, 20, 30, 40, 50, 60, 70, 80, 90]    #힐 / 베르 HP % 드롭다운
MOB_CHOICES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]         #이뮨 몹 수 드롭다운
RANGES = [('near', '근거리'), ('far', '원거리')]   #표시 순서

BUFFS   = []      # [(트리거명, 키, 주기(초))]  주기 0 = 비활성
BUFFKEY = {}      # 트리거명 -> 키

KEY_REFRESH        = None   #사냥 헛돌 때 새로고침
KEY_TRANSFORM      = None   #변신
KEY_RETURN         = None   #귀환 (역할에서 뺐다. 항상 None)
ATTACKS            = []     #공격 키 [(키, 딜레이(초), 거리(타일)), ...]  공격 탭 순서 = 우선순위
KEY_SKILL          = None   #(호환) 공격 키 1번의 키. pit.py 가 아직 이 이름을 쓴다
SKILL_COOL         = 0      #(호환) 공격 키 1번의 딜레이(초). 0 이면 끔
                            #타이머가 아니라 사냥 루프 안에서 '공격 중인 시간' 만 누적해서 잰다
                            #-> 버프/변신으로 공격이 멈춘 동안, 공격을 껐을 때는 쿨타임도 같이 멈춘다
TRANSFORM_INTERVAL = 0      #변신 주기(초). 0 이면 변신 안 함
ATTACK_ON          = True   #공격 사용 여부. 끄면 서치를 안 하고 수동 사냥 보조로 돈다
                            #(사람이 마우스를 움직이고, 대상 위에 커서가 올라가면 휠 클릭만 대신 눌러준다)
MANUAL_POLL        = 0.03   #수동 사냥 : 커서 모양을 보는 간격(초)
MANUAL_CLICK_GAP   = 0.2    #수동 사냥 : 휠 클릭 한 번 누르고 다음 클릭까지 최소 간격(초). 연타 방지
SCAN_ROUND         = SCAN_NEAR              #현재 탐지 거리의 바퀴 수
NOHIT_LIMIT        = DEFAULT_OPTS['nohit']  #헛돌 때 새로고침까지의 횟수
SOUND_ON           = DEFAULT_OPTS['sound']  #소리 감지 사용 여부
HUNT_DIST          = DEFAULT_OPTS['dist']   #사냥 탐지 거리(타일)
DETECT_ONLY        = DEFAULT_OPTS['detect'] #감지만 (클릭/귀환 안 함)

#--- 메모리 사냥 ---
#몹 위치와 주변 캐릭터는 엔티티 테이블(memread)에서 읽는다. 화면을 훑지 않는다
#몹의 화면 좌표는 보정 파일(게임 좌표 차이 -> 화면 픽셀 아핀 변환)로 구한다
#  scarecrow_calib.json (postracker.py 의 허수아비 보정) > calib.json (turnundead_mem.py 의 보정)
HUNT_POLL      = 0.1    #사냥 루프 한 바퀴 간격(초)
RECLICK_SEC    = 0.5    #클릭 간격(초). 클릭할 때마다 가장 가까운 몹을 다시 고른다
#벽 너머 몹 걸러내기 : 지형(벽) 자체는 메모리에서 못 읽는다. 대신 '다가가지 못하는 몹' 을 본다.
#대상이 STUCK_REACH 타일보다 먼데 STUCK_SEC 동안 내 좌표도 안 바뀌고 거리도 안 줄면
#막힌 것으로 보고 SKIP_SEC 동안 그 몹을 대상에서 뺀다. 남은 몹이 없으면 평소처럼 텔한다
STUCK_REACH    = 2      #이 거리(타일) 안이면 붙어서 싸우는 중으로 보고 막힘 판정을 안 한다
STUCK_SEC      = 4.0    #이만큼 진전이 없으면 막힌 것으로 본다
SKIP_SEC       = 20.0   #막힌 몹을 대상에서 빼 두는 시간
IDLE_TELE_SEC  = 10.0   #같은 대상을 잡은 채 이만큼 아무 변화(대상 바뀜/끝/텔)가 없으면 강제로 텔한다
TELE_DELAY     = 0.5    #몹이 없다고 판단한 뒤 텔 키를 누르기까지 두는 시간(초)
TELE_GAP       = 1.5    #텔(새로고침 키)을 누른 뒤 다음 텔까지 최소 간격(초). 이동 뒤 주변이 다시 읽힐 시간
MEM_FAIL_LIMIT = 10     #엔티티 테이블을 연속으로 이만큼 못 읽으면 멈춘다 (화면으로 넘어가지 않는다)
CALIB_FILES    = ['scarecrow_calib.json', 'calib.json']   #앞엣것 우선
#--- 힐 / 베르 / 이뮨 ---
#사냥 루프가 매 바퀴 HP 와 주위 몹 수를 보고 해당 키를 누른다 (키는 역할 표에서 지정)
#재사용 간격은 그 키의 주기(초) 칸 값이고, 0 이면 아래 기본값을 쓴다
KEY_HEAL    = None
KEY_BER     = None
KEY_IMMUNE  = None
HEAL_PCT    = DEFAULT_OPTS['heal_pct']
BER_PCT     = DEFAULT_OPTS['ber_pct']
IMMUNE_N    = DEFAULT_OPTS['immune_n']
HEAL_GAP    = 2.0     #힐을 다시 누르기까지 최소 간격(초)
BER_GAP     = 2.0
IMMUNE_GAP  = 30.0
GAP_DEFAULT = {'heal': 2.0, 'ber': 2.0, 'immune': 30.0}   #주기 칸이 0 일 때 쓰는 간격
INFO_POLL   = 500     #내 캐릭터 정보 표시 갱신 간격(ms)
MEM            = None   #memread.Mem. runmacro 가 붙이고 뗀다
CASTER         = None   #memcast.Caster. 힐 / 이뮨을 내 캐릭터에게 걸 때 쓴다 (postracker.py 의 턴언데드와 같은 방식)
CALIB          = None   #아핀 계수 (a,b,c,d,e,f). 화면 = (a*dx+b*dy+c, d*dx+e*dy+f)

#=====================================================================
# 트리거 : 한 순간에 하나만 True
#  - TRIGGER 를 바꾸는 것도, 키/마우스를 쓰는 것도 매크로 스레드뿐이다
#  - 타이머 스레드는 PENDING 에 요청만 남기고 물러난다 (마우스 겹침 원천 차단)
#  - GUI 스레드는 입력을 절대 보내지 않는다
#=====================================================================
ALIVE  = False
HOTKEY = None     #tab 핫키 핸들. 정지할 때 떼어낸다
HUNT_START = None #사냥 루프에 들어간 시각(time.time()). 종료 때 사냥 시간을 찍는 데 쓴다
                  #카운트다운/캘리브레이션은 사냥이 아니므로 huntloop 직전에 잡는다

#소리로 판단한 칼질 상태. 소리 스레드가 쓰고 사냥 루프가 읽는다
#bool 하나만 주고받으므로 락은 두지 않는다 (한 박자 늦게 읽어도 다음 프레임에 맞춰진다)
FIGHTING    = False   #True 면 마우스 서치를 멈춘다
FIGHT_READY = False   #소리 감시가 실제로 도는 중인지
                      #루프백을 못 열면 False 라서 게이트가 통째로 꺼지고 예전처럼 계속 서치한다

TRIGGER ={'hunt': False, 'stop': False, 'transform': False, 'return': False, 'chatbuff': False}
ORDER   = ['stop', 'return', 'transform', 'chatbuff']   #처리 우선순위 : 정지 > 귀환 > 버프 > 변신 > 채팅버프 (채팅버프는 맨 뒤. 채팅 뒤에 누른 키는 채팅칸에 먹혀 안 들어간다)

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
    log('요청 등록 : ' + str(name))      #사냥 루프가 이걸 꺼내 실행한다

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
        #ORDER 에 없는 이름으로 요청이 들어오면 영원히 안 꺼내진다. 그 경우를 잡아낸다
        if len(PENDING) > 0:
            stuck = ', '.join(sorted(PENDING.keys()))
            PENDING.clear()
            log('처리 못 한 요청 버림 : ' + stuck + '  (ORDER = ' + ', '.join(ORDER) + ')')
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
    gu.moveTo(centerpoint[0],centerpoint[1]-225)
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
#채팅버프는 k.write 로 유니코드를 바로 넣어서 IME 를 안 타므로 아직 쉼
#게임이 IME 를 거쳐야만 글자를 받는다면 dochatbuff() 앞뒤에서 되살린다
# VK_HANGUL       = 0x15
# KEYEVENTF_KEYUP = 0x0002
#
# def _togglehangul():
#     win32api.keybd_event(VK_HANGUL, 0, 0, 0)
#     time.sleep(0.05)
#     win32api.keybd_event(VK_HANGUL, 0, KEYEVENTF_KEYUP, 0)
#     time.sleep(0.2)

#=====================================================================
# 실행부 : 전부 매크로 스레드에서만 돈다
#=====================================================================

#버프 : F키 한 번
def dobuff(name):
    key = BUFFKEY[name]
    log(name + ' 버프 : ' + key)
    gu.press(key, presses=1)
    time.sleep(BUFF_KEY_GAP)     #다음 버프 키까지. 쌓인 버프는 runpending 이 이 간격으로 하나씩 누른다

#단축키 페이지를 바꾼다 (F1 = 공격, F2 = 버프)
def setpage(key):
    log('단축키 페이지 : ' + key.upper())
    gu.press(key, presses=1)
    time.sleep(PAGE_GAP)

#채팅버프 : 엔터로 채팅창을 열고 '.버프' 를 쳐서 엔터로 보낸다
#글자는 채팅 입력칸 메모리에 바로 써 넣는다 (memchat.py). 키로 치면 한/영 상태에 따라
#'.버프' 가 '.qjvm' 로 들어가서 명령이 안 먹었다. 채팅칸 열기와 전송만 엔터 키로 한다
#빈 입력칸에는 글자 버퍼가 아직 없으므로(게임이 첫 글자 때 만든다) 한/영과 상관없는 숫자 키를
#글자 수만큼 먼저 쳐서 자리를 만들고, 그 자리를 명령어로 덮어쓴다
CHAT_FILL = '1'       #자리 만들기용 키. 한글 입력 상태에서도 그대로 들어가는 글자여야 한다

def dochatbuff():
    log('채팅버프 : ' + CHAT_CMD)
    usemem = (MEM != None
              and ((MEM.cfg or {}).get('chains') or {}).get('chat_str') != None)
    gu.press('enter', presses=1)          #채팅창 열기
    time.sleep(CHAT_GAP)
    if usemem:
        import memchat
        gu.press(CHAT_FILL, presses=len(CHAT_CMD), interval=0.05)
        time.sleep(CHAT_GAP)
        chat = memchat.Chat(MEM)
        okay = chat.put(CHAT_CMD)
        chat.close()
        if not okay:
            #덮어쓰지 못했으면 쳐 둔 숫자를 지우고 아무것도 보내지 않는다. 빈 채팅칸은 엔터로 닫힌다
            log('채팅버프 실패 : ' + str(chat.err))
            gu.press('backspace', presses=len(CHAT_CMD) + 2, interval=0.03)
    else:
        #mem.json 에 chat_str 가 없을 때의 예전 방식 (pit.py 도 이 길로 온다)
        k.write(CHAT_CMD, delay=0.05)         #유니코드로 직접 주입 (IME 안 거침)
    time.sleep(CHAT_GAP)
    gu.press('enter', presses=1)          #전송
    time.sleep(BUFF_GAP)

#변신
def dotransform():
    log('변신 : ' + str(KEY_TRANSFORM))
    time.sleep(TRANSFORM_WAIT)            #앞 버프의 시전 중에 누르면 변신 키가 씹힌다
    gu.press(KEY_TRANSFORM, presses=1)
    file_path = IMAGE_DIR
    #메뉴가 뜨는 데 걸리는 시간이 들쭉날쭉해서 한 번만 보지 않고 잠깐 동안 다시 찾는다
    lv80 = None
    deadline = time.time() + TRANSFORM_MENU_SEC
    while lv80 == None and time.time() < deadline:
        time.sleep(TRANSFORM_MENU_POLL)
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
    if KEY_RETURN == None:
        log('귀환 키 없음 (역할에서 뺐다) - 정지만 한다')
        dostop()
        return
    log('귀환 : ' + str(KEY_RETURN))
    gu.press(KEY_RETURN, presses=1)
    dostop()

#대기 중인 트리거를 꺼내 실행. 실행했으면 True
#버프 / 변신은 버프 페이지(F2) 의 키라서 F2 로 바꾸고 누른 뒤 F1 로 돌아온다
#쌓인 요청은 한 번의 페이지 전환으로 몰아서 처리한다 (시작할 때 버프를 전부 걸고 F1 로 가는 것도 이 길)
#사냥 트리거 False -> 해당 트리거 True -> 동작 -> 사냥 트리거 True 복귀
def runpending():
    name = takepending()
    if name == None:
        return False

    onbuff = False                #지금 F2 페이지에 있는지
    while name != None:
        settrigger(name)          #사냥 트리거는 여기서 자동으로 False
        if name == 'stop':
            dostop()
            return True           #사냥 트리거 복구 안 함. ALIVE=False 로 루프가 끝난다
        if name == 'return':
            doreturn()            #안에서 dostop() 을 부른다
            return True
        if name == 'chatbuff':
            #채팅을 보낸 뒤에는 입력칸에 포커스가 남아 다음 키가 씹힌다. 그래서 ORDER 의 맨 뒤이고,
            #F2 페이지였다면 채팅 전에 F1 로 먼저 돌아온다 (채팅 뒤의 F1 은 안 먹을 수 있다)
            if onbuff:
                setpage(PAGE_ATTACK)
                onbuff = False
            dochatbuff()
        else:
            if not onbuff:
                setpage(PAGE_BUFF)
                onbuff = True
            if name == 'transform':
                dotransform()
            else:
                dobuff(name)
        name = takepending()
    if onbuff:
        setpage(PAGE_ATTACK)
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

#채팅버프(.버프) : 20분마다. F키를 안 쓰므로 버프 슬롯과 따로 돈다
def chatbufftimer():
    if not ALIVE:
        return
    request('chatbuff')
    _arm(CHAT_INTERVAL, chatbufftimer)

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

#image 폴더에 들어있는 마크 이미지(png/bmp)를 긁어온다
#  - MARK_MAX 까지만 본다. mark4.PNG 를 폴더에 둬도 MARK_MAX 가 3 이면 안 본다
#  - 같은 번호의 png 와 bmp 가 둘 다 있으면 bmp(원본)를 우선한다
#  - 번호가 없는 bmp(예: 5149.bmp)도 마크 후보에 넣는다. 번호 있는 것들 뒤에 붙는다
#  - 번호 순으로 정렬해서 mark1, mark2 ... 순서로 본다 (mark10 이 mark2 앞에 오지 않게)
#  - 한 번 읽고 캐시한다. 사냥 중에 폴더를 뒤지지 않기 위함
MARK_FILES = None

#'mark3.bmp' -> 3. 번호가 없으면 None
def marknum(name):
    digits = ''
    for ch in os.path.splitext(name)[0][len('mark'):]:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits) if digits != '' else None

def markfiles():
    global MARK_FILES
    if MARK_FILES != None:
        return MARK_FILES

    #png(화면 캡처)와 bmp(혈맹문장 원본)를 둘 다 긁어온다
    found = []
    for pat in (MARK_GLOB, 'mark*.png', 'mark*.bmp'):
        found += glob.glob(IMAGE_DIR + pat)
    #윈도우 glob 은 대소문자를 안 가려서 같은 파일이 두 번 잡힌다. 번호 기준으로 중복 제거
    #같은 번호가 png/bmp 둘 다 있으면 bmp(원본+마스크)를 우선한다
    seen = {}
    for path in found:
        name = os.path.basename(path)
        num  = marknum(name.lower())
        if num == None:                       #mark.bmp, markold.bmp 같은 건 건너뛴다
            continue
        if MARK_MAX > 0 and num > MARK_MAX:   #MARK_MAX 를 넘는 번호는 안 본다
            continue
        if num in seen and not name.lower().endswith('.bmp'):
            continue                          #이미 bmp 가 잡혀 있으면 png 는 버린다
        seen[num] = path
    MARK_FILES = [seen[num] for num in sorted(seen.keys())]

    #번호가 없는 bmp(예: 5149.bmp)도 마크 후보에 넣는다. 번호 있는 것들 뒤에 붙인다
    for path in sorted(glob.glob(IMAGE_DIR + '*.bmp')):
        name = os.path.basename(path)
        if marknum(name.lower()) != None:
            continue                          #번호 있는 건 위에서 처리됨
        if name.lower() in [os.path.basename(p).lower() for p in MARK_FILES]:
            continue
        MARK_FILES.append(path)

    limit = ('mark1~' + str(MARK_MAX)) if MARK_MAX > 0 else '전부'
    if len(MARK_FILES) == 0:
        log('마크 이미지 없음 : ' + IMAGE_DIR + MARK_GLOB + ' (' + limit + ') 에 파일이 하나도 없다')
    else:
        log('마크 이미지 ' + str(len(MARK_FILES)) + '개 (' + limit + ') : '
            + ', '.join([os.path.basename(x) for x in MARK_FILES]))
    return MARK_FILES

#내 마크 자리인지. 마크 매칭 중심 (x, y) 를 받아 MARK_SELF_OFFSETS 의 자리들과 거리를 잰다
def isselfmark(x, y):
    if MARK_SELF_RADIUS <= 0:
        return False
    for off in MARK_SELF_OFFSETS:
        sx = CENTERPOINT[0] + off[0]
        sy = CENTERPOINT[1] + off[1]
        if math.hypot(x - sx, y - sy) <= MARK_SELF_RADIUS:
            return True
    return False

#하단 UI 영역인지. HP바/채팅창이 있는 맨 아래쪽에서 잡힌 매칭은 UI 오탐이므로 버린다
#h 는 화면 높이(px). MARK_BOTTOM_CUT=0.88 이면 아래쪽 12% 는 안 본다
def isbottomui(x, y, h):
    if MARK_BOTTOM_CUT >= 1.0:
        return False
    return y > h * MARK_BOTTOM_CUT

#마크 템플릿 캐시 : 경로 -> (그림 float32, 마스크 float32, 마스크 픽셀수)
#혈맹문장 BMP 는 검정이 게임에서 투명으로 렌더링된다. 그 검정까지 비교하면
#'어두운 네모' 를 찾는 꼴이라 배경에서 오탐이 쏟아진다. 그래서 검정을 마스크로 빼고 본다
_MARK_TPL = {}

def _marktpl(path):
    tpl = _MARK_TPL.get(path)
    if tpl != None:
        return tpl
    #cv2.imread 는 한글 경로에서 None 을 돌려준다. fromfile + imdecode 로 우회한다
    img = cv2.imdecode(numpy.fromfile(path, dtype=numpy.uint8), cv2.IMREAD_COLOR)
    if img is None:
        log('마크 이미지를 못 읽음 : ' + path)
        tpl = (None, None, 0)
    else:
        if MARK_BG_TOL > 0:
            keep = (img.max(axis=2) > MARK_BG_TOL)      #검정이 아닌 = 실제 그림
        else:
            keep = numpy.ones(img.shape[:2], dtype=bool)
        cnt = int(keep.sum())
        if cnt == 0:
            log('마크 이미지가 전부 배경색 : ' + os.path.basename(path))
            tpl = (None, None, 0)
        else:
            mask = numpy.dstack([keep.astype('float32')] * 3)
            tpl  = (img.astype('float32'), mask, cnt)
            log('마크 ' + os.path.basename(path) + ' : 그림 ' + str(cnt)
                + '/' + str(keep.size) + 'px 만 비교 (검정 배경 제외)')
    _MARK_TPL[path] = tpl
    return tpl

#지금 화면을 BGR float32 로 한 장 찍는다. 마크 여러 개를 한 장으로 돌리기 위함
def screengrab():
    return numpy.array(gu.screenshot().convert('RGB'))[:, :, ::-1].astype('float32')

#마크 하나를 화면에서 찾는다. 내 캐릭터 자리에 뜬 건 건너뛰고,
#그 밖에서 잡힌 가장 잘 맞는 매칭의 중심 (x, y) 를 돌려준다. 없으면 None
def findmark(hay, path, conf):
    #bmp 원본에만 마스크를 쓴다 (1번 방법). 검정이 게임에서 투명으로 렌더링되기 때문
    #png 화면 캡처는 배경이 진짜라서 마스크를 끄면 예전 방식이 더 낫다. 밝기 변화에 덜 흔들린다
    use_mask = path.lower().endswith('.bmp') and MARK_BG_TOL > 0 and MASK_OK and hay is not None
    if not use_mask:
        return _findmark_old(path, conf)

    needle0, mask0, cnt0 = _marktpl(path)
    if needle0 is None:
        return None
    h0, w0 = needle0.shape[0], needle0.shape[1]

    #스케일 피라미드: 화면의 실제 마크 크기를 모르므로 여러 배율로 돌려 최고점을 고른다
    best = None  # (점수, x, y)
    for s in MARK_SCALES:
        w, h = int(w0 * s), int(h0 * s)
        if w < 1 or h < 1 or w > hay.shape[1] or h > hay.shape[0]:
            continue
        if s == 1.0:
            needle, mask, cnt = needle0, mask0, cnt0
        else:
            #템플릿을 키운다. 마스크는 보간 뒤 다시 threshold 해서 경계를 살린다
            needle = cv2.resize(needle0, (w, h), interpolation=cv2.INTER_CUBIC)
            keep = cv2.resize(mask0[:, :, 0], (w, h),
                              interpolation=cv2.INTER_NEAREST) > 0.5
            cnt = int(keep.sum())
            if cnt == 0:
                continue
            mask = numpy.dstack([keep.astype('float32')] * 3)

        #마스크 밖(검정)은 빼고, 남은 픽셀의 색 차이만 본다
        #TM_SQDIFF 는 (차이 x 마스크)^2 의 합이라 마스크 픽셀만 더해진다
        res = cv2.matchTemplate(hay, needle, cv2.TM_SQDIFF, mask=mask)
        res = numpy.where(numpy.isfinite(res), res, numpy.inf)  #마스크가 0 인 자리는 버린다
        #픽셀당 평균 오차로 바꿔서 0~1 점수로 만든다. 1.0 이면 그림이 완전히 같다
        #(cnt 로 나누므로 스케일이 달라도 점수끼리 비교가 된다)
        score = 1.0 - numpy.sqrt(numpy.clip(res, 0, None) / (cnt * 3.0)) / 255.0

        ys, xs = numpy.where(score >= conf)
        #잘 맞는 것부터 본다. 내 마크 자리나 하단 UI 면 건너뛰고 다음 후보로
        for i in numpy.argsort(-score[ys, xs]):
            x = int(xs[i]) + w // 2
            y = int(ys[i]) + h // 2
            if isselfmark(x, y):
                continue
            if isbottomui(x, y, hay.shape[0]):
                continue
            sc = float(score[ys[i], xs[i]])
            if best is None or sc > best[0]:
                best = (sc, x, y)
            break  #이 스케일에서는 최고점 하나만 본다
    if best is None:
        return None
    return (best[1], best[2])

#cv2/numpy 가 없을 때 쓰는 예전 방식. 검정 배경까지 그대로 비교한다
def _findmark_old(path, conf):
    sw, sh = gu.size()
    for box in gu.locateAllOnScreen(path, confidence=conf):
        x = box.left + box.width  // 2
        y = box.top  + box.height // 2
        if isselfmark(x, y):
            continue
        if isbottomui(x, y, sh):
            continue
        return (x, y)
    return None

#피 확인. 이미지 매칭은 입력을 안 건드리므로 스레드에서 해도 안전
def checkrHp():
    if not ALIVE:
        return
    try:
        _checkrHp()
    except Exception as e:
        #타이머 스레드에서 터지면 stderr 이 없는 exe 에서는 아무 말 없이 감시가 끊긴다
        log('피/마크 감시 오류 : ' + str(e))
        log(traceback.format_exc())
        _arm(HP_INTERVAL, checkrHp)      #한 번 터졌다고 감시를 놓지는 않는다

def _checkrHp():
    file_path = IMAGE_DIR

    #1. 피 부족 경고 UI 가 '뜨면' 귀환
    #(감지만 모드에서는 귀환을 안 하므로 건너뛴다)
    if (not DETECT_ONLY) and gu.locateCenterOnScreen(file_path + HP_IMG, confidence=HP_CONF) != None:
        log('피 소모 완료 귀환!')
        request('return')
        return                #매크로 루프가 처리하고 종료하므로 타이머 재등록 안 함

    #2. 주변에 다른 캐릭터가 있으면 귀환 (엔티티 테이블. 마크 이미지는 더 이상 안 본다)
    global WATCH_FAIL, WATCH_SEEN
    found = scanents()
    if found == None or found['players'] == None:
        #못 읽은 것을 '아무도 없음' 으로 치면 감시가 조용히 죽는다. 연속으로 못 읽으면 멈춘다
        WATCH_FAIL += 1
        if WATCH_FAIL >= MEM_FAIL_LIMIT:
            log('주변 캐릭터를 ' + str(WATCH_FAIL) + '번 연속 못 읽었다 - 정지')
            request('stop')
            return
    else:
        WATCH_FAIL = 0
        others = found['players']
        if len(others) > 0:
            names = ', '.join(str(o.get('name')) + '(거리 ' + str(d) + ')' for d, o, pos in others)
            if not DETECT_ONLY:
                log('다른 캐릭터 발견 : ' + names + ' 귀환!')
                request('return')
                return
            ids = set(o['id'] for d, o, pos in others)
            if ids != WATCH_SEEN:        #감지만 : 바뀔 때만 찍는다
                log('[감지만] 다른 캐릭터 : ' + names)
            WATCH_SEEN = ids
        elif DETECT_ONLY and len(WATCH_SEEN) > 0:
            log('[감지만] 다른 캐릭터 없음')
            WATCH_SEEN = set()

    _arm(HP_INTERVAL, checkrHp)

WATCH_FAIL = 0        #주변 캐릭터 판정을 연속으로 못 한 횟수
WATCH_SEEN = set()    #감지만 모드에서 마지막으로 찍은 캐릭터 id 들

#예전 방식 : 적대 혈맹 마크 이미지 찾기. main.py 는 더 이상 부르지 않는다
#(pit.py 가 같은 코드를 따로 갖고 있다. 기록용으로 남겨 둔다)
def _checkmarks():
    marks = markfiles()
    #마스크를 쓸 때만 화면을 한 장 찍어 돌려쓴다. 예전 방식은 자기가 알아서 찍는다
    need_hay = (MARK_BG_TOL > 0 and MASK_OK
                and any(m.lower().endswith('.bmp') for m in marks))
    hay   = screengrab() if (need_hay and len(marks) > 0) else None
    for markpath in marks:
        markname = os.path.basename(markpath)
        markconf = MARK_CONF_BY_FILE.get(markname, MARK_CONF)
        found = findmark(hay, markpath, markconf)
        if found != None:
            log('적대 마크 발견 (' + markname + ' @ ' + str(found[0]) + ',' + str(found[1]) + ') 귀환!')
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
#예전 방식 : 커서로 캐릭터 주변을 훑다가 공격 커서가 뜨면 클릭. main.py 는 더 이상 부르지 않는다
#(다른 던전용 기록으로 남겨 둔다. 지금 사냥은 아래 huntloop 이다)
def huntloop_sweep(p, atkvalue):
    points  = _scanpoints(p)
    #파크는 가장 바깥 바퀴보다 더 아래. 안 그러면 5배 바퀴의 6시 점과 겹친다
    #근거리로 좁혀도 파크 자리는 안 움직이게 SCAN_FAR 기준으로 고정한다
    parkpos = (p[0], p[1] + SCAN_START * SCAN_FAR + PARK_GAP)
    cnt     = 0       #클릭 없이 헛돈 횟수 (칼질하면 초기화)
    loopcnt = 0       #공격 루프 누적 횟수 (새로고침될 때만 초기화)
    idx     = 0       #지금 볼 스캔점 번호. 전투로 멈췄다 이어 돌려고 while 밖에 둔다

    #공격스킬 쿨타임. 실제 시계가 아니라 '공격 중이던 시간' 만 더한다
    #시작할 때는 꽉 채워둬서 첫 대상을 치자마자 한 번 쓴다
    skillon  = ATTACK_ON and KEY_SKILL != None and SKILL_COOL > 0
    skillsec = float(SKILL_COOL)
    tick     = time.perf_counter()   #마지막으로 쿨타임을 더한 시각

    #쿨타임이 차 있으면 스킬을 누른다. 대상을 클릭한 직후와 칼질 중에만 부른다
    def useskill(why):
        if skillon and skillsec >= SKILL_COOL:
            log('스킬 ' + KEY_SKILL.upper() + ' (' + why + ')')
            gu.press(KEY_SKILL, presses=1)
            return True
        return False

    if ATTACK_ON:
        radii = ','.join(str(SCAN_START * (i + 1)) for i in range(SCAN_ROUND))
        log('서치 : ' + ('근거리' if SCAN_ROUND <= SCAN_NEAR else '원거리')
            + '  ' + str(SCAN_DIRS) + '방향 x ' + str(SCAN_ROUND) + '바퀴'
            + '  반지름 ' + radii + '  총 ' + str(len(points)) + '점')
        log('파크 : ' + str(parkpos[0]) + ',' + str(parkpos[1]))

    if skillon:
        log('공격스킬 : ' + KEY_SKILL.upper() + '  쿨타임 ' + str(SKILL_COOL) + '초 (공격 중에만 흐름)')

    settrigger('hunt')
    while ALIVE:
        if runpending():       #버프/변신/귀환이 먼저. 처리했으면 처음부터
            tick = time.perf_counter()   #버프/변신에 쓴 시간은 공격이 아니므로 쿨타임에서 뺀다
            continue

        #공격 꺼짐 : 수동 사냥 보조. 커서는 안 움직이고, 사람이 올려둔 자리가 대상이면 휠 클릭만 누른다
        #(구버전 main2.py 의 수동사냥 루프. 우클릭을 사람이 직접 안 눌러도 되게 한다)
        if not ATTACK_ON:
            if win32gui.GetCursorInfo()[1] == atkvalue:
                gu.middleClick()
                time.sleep(MANUAL_CLICK_GAP)
            else:
                time.sleep(MANUAL_POLL)
            continue

        #여기부터가 공격 중. 지난 틱 이후 흐른 시간을 쿨타임에 더한다
        now      = time.perf_counter()
        skillsec += now - tick
        tick      = now

        #칼질 소리가 들리면 이미 몹을 잡고 있는 것이므로 커서를 아예 안 건드린다
        #idx 를 그대로 두므로 소리가 끊기면 멈춘 자리(중간)에서 이어서 돈다
        if FIGHT_READY and FIGHTING:
            if useskill('칼질 중'):      #몹을 잡는 중에 쿨이 차면 바로 쓴다
                skillsec = 0.0
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
            if useskill('공격 후'):      #대상을 치고 나서 쿨이 차 있으면 스킬
                skillsec = 0.0
            cnt = 0
            if not FIGHT_READY:
                idx = 0         #소리 감시가 없으면 예전처럼 1바퀴 첫 방향부터 다시 스캔
                                #(소리가 있으면 곧 칼질로 멈추고, 끝난 뒤 다음 점부터 이어 돈다)

#=====================================================================
# 메모리 사냥 : 엔티티 테이블에서 몹 위치를 읽어 가까운 순으로 클릭
#=====================================================================

#보정 파일을 읽어 아핀 계수를 돌려준다. (계수, 파일 이름) 또는 (None, 사유)
#점 = (게임 좌표 차이 dx, dy, 화면 x, y). 3점 이상이어야 한다
def loadcalib():
    import turnundead_mem as tm      #아핀 풀이(순수 계산)를 빌려 쓴다
    why = '보정 파일 없음 (' + ' / '.join(CALIB_FILES) + ')'
    for name in CALIB_FILES:
        path = os.path.join(APP_DIR, name)
        if not os.path.isfile(path):
            continue
        try:
            f = open(path, 'r', encoding='utf-8')
            data = json.load(f)
            f.close()
            pts = [(float(q[0]), float(q[1]), float(q[2]), float(q[3]))
                   for q in data.get('points', [])]
        except Exception as e:
            why = name + ' 읽기 실패 : ' + str(e)
            continue
        coef = tm.fit_affine_nocheck(pts)
        if coef == None:
            why = name + ' 의 점이 모자라거나 한 줄로 늘어서 있다 (' + str(len(pts)) + '점)'
            continue
        return coef, name + ' (' + str(len(pts)) + '점)'
    return None, why

#게임 좌표 차이 -> 화면 좌표. 보정이 없으면 None
def toscreen(dx, dy):
    if CALIB == None:
        return None
    a, b, c, d, e, f = CALIB[:6]
    return (int(round(a * dx + b * dy + c)), int(round(d * dx + e * dy + f)))

#엔티티 테이블을 한 번 읽어 정리한다. 못 읽었거나 나를 못 찾으면 None (= 판정 불가)
#  'me'      : 내 엔티티,  'pos' : 내 게임 좌표
#  'mobs'    : [(거리, 엔티티, 게임좌표)] 살아 있는 사냥 대상. 가까운 순. HUNT_DIST 안만
#  'players' : [(거리, 엔티티, 게임좌표)] 나 말고 다른 캐릭터. player 규칙이 없으면 None
#거리는 타일 수 (가로세로 중 큰 쪽)
#사냥 대상 : mem.json ent.rules 에 monster 규칙이 있으면 그 종류만,
#            없으면 '캐릭터가 아닌 것 전부' 를 대상으로 삼는다 (이름 없는 것은 뺀다)
def scanents():
    if MEM == None:
        return None
    ents, head, count = MEM.entity_table()
    if len(ents) == 0:
        return None
    me = MEM.selfent(ents)
    if me == None:
        return None
    mpos   = MEM.entpos(me)
    kinds  = MEM.entkinds()
    mobs   = []
    people = [] if 'player' in kinds else None
    for o in ents:
        if o['ptr'] == me['ptr']:
            continue
        pos  = MEM.entpos(o)
        dist = max(abs(pos[0] - mpos[0]), abs(pos[1] - mpos[1]))
        kind = MEM.kind(o)
        if kind == 'player':
            people.append((dist, o, pos))
            continue
        if o['dead'] or dist > HUNT_DIST:
            continue
        if not o.get('name'):
            continue      #이름이 없는 것은 몹이 아니다 (실기: 내 자리에 겹쳐 있던 id 68363, 거리 0)
        if 'monster' in kinds and kind != 'monster':
            continue
        if 'monster' not in kinds and kind != 'other':
            continue      #이펙트처럼 다른 종류로 판정된 것은 사냥 후보에서도 뺀다
        mobs.append((dist, o, pos))
    mobs.sort(key=lambda r: r[0])
    if people != None:
        people.sort(key=lambda r: r[0])
    return {'me': me, 'pos': mpos, 'mobs': mobs, 'players': people}

#지금 HP 와 최대 HP. (hp, 최대) 또는 None (못 읽음 / 값이 이상함)
#현재 HP 는 보안 홀더(mem.json secure)를 먼저 보고, 없으면 chains.hp 를 본다 (memread.charinfo 와 같다)
def readhp(mem=None):
    if mem == None:
        mem = MEM
    if mem == None:
        return None
    hp = mem.secure_value('hp') if (mem.cfg or {}).get('secure') else None
    if hp == None:
        hp = mem.value('hp')
    mx = mem.value('char_hp_max')
    if mx == None:
        mx = mem.value('hp_max')
    if hp == None or mx == None or mx <= 0 or hp < 0 or hp > mx * 2:
        return None
    return hp, mx

#힐 / 이뮨처럼 대상을 골라야 나가는 마법을 내 캐릭터에게 건다.
#키만 누르면 대상 선택 상태에서 멈추므로, postracker.py 가 턴언데드를 쓰는 것과 같이
#memcast 로 '마법 대상' 칸에 내 id 를 잠깐 써넣고 키를 누른 뒤 원래 값으로 되돌린다
#me = scanents() 가 준 내 엔티티. 시전됐으면 True, 아니면 사유를 로그에 남기고 False
def selfcast(key, me, label):
    if CASTER == None:
        log(label + ' 실패 : 시전 모듈이 없다')
        return False
    res = CASTER.castkey(me['id'], me['ptr'], key)
    if res['state'] != 'sent':
        log(label + ' ' + key.upper() + ' : ' + str(res['msg']) + ' (' + str(res['state']) + ')')
        return False
    return True

#지금 레벨 / 누적 경험치 / 경험치 %. (레벨, 경험치, %) 또는 None (못 읽음)
def readexp():
    if MEM == None:
        return None
    lv  = MEM.value('char_level')
    exp = MEM.value('char_exp')
    if lv == None or exp == None:
        return None
    return lv, exp, MEM.exppct(lv, exp)

#사냥을 시작할 때와 끝날 때의 경험치를 비교해 한 줄로 만든다. 늘어난 수치만 간결하게
def fmtexp(a, b):
    if a == None or b == None:
        return '경험치 : 못 읽음'
    gain = b[1] - a[1]
    line = '경험치 : ' + ('+' if gain >= 0 else '') + '{:,}'.format(gain)
    if a[0] == b[0] and a[2] != None and b[2] != None:
        diff = b[2] - a[2]
        line += ' (' + ('+' if diff >= 0 else '') + '%.2f' % diff + '%)'
    elif b[0] > a[0]:
        line += ' (레벨 ' + str(b[0] - a[0]) + ' 상승)'
    return line

#소지 아데나. 인벤토리 창에서 이름이 '아데나' 인 항목의 개수. 못 읽으면 None
ADENA_NAME = '아데나'
def readadena():
    if MEM == None:
        return None
    try:
        items, win, count = MEM.item_table()
    except Exception:
        return None
    for it in items:
        nm = it.get('name')
        if nm != None and nm.startswith(ADENA_NAME):
            return it.get('count')
    return None

#시작과 끝의 아데나 차이를 한 줄로
def fmtadena(a, b):
    if a == None or b == None:
        return '아데나 : 못 읽음'
    diff = b - a
    return '아데나 : ' + ('+' if diff >= 0 else '') + '{:,}'.format(diff)

#사냥 루프 (매크로 스레드)
#  가장 가까운 몹을 클릭하고, 그 몹이 죽거나 사라지면 다음으로 가까운 몹으로 넘어간다
#  클릭할 차례(RECLICK_SEC)마다 더 가까운 몹이 생겼는지 다시 보고, 있으면 그쪽으로 바꾼다
#  공격 커서(칼 모양) 확인은 하지 않는다 : 계산한 화면 좌표를 그대로 클릭한다 (2026-11-15 사용자 결정).
#  확인에 실패한 몹을 잠깐 제쳐 두던 것 때문에, 몹이 있는데도 '몹 없음' 으로 보고 텔하는 일이 있었다
#p, atkvalue 는 예전 huntloop 과 자리를 맞추려고 남겨 둔 인자다 (쓰지 않는다)
def huntloop(p=None, atkvalue=None):
    screen  = gu.size()
    target  = None     #지금 잡고 있는 몹의 id
    tname   = ''
    clicked = 0.0      #마지막으로 클릭한 시각
    fail    = 0        #테이블을 연속으로 못 읽은 횟수
    teled   = 0.0      #마지막으로 텔(새로고침 키)을 누른 시각
    pressed = {'heal': 0.0, 'ber': 0.0, 'immune': 0.0}   #힐 / 베르 / 이뮨을 마지막으로 누른 시각
    skip    = {}       #id -> 다시 대상으로 삼아도 되는 시각 (다가가지 못한 몹)
    moved   = time.perf_counter()   #사냥에 마지막으로 변화가 있던 시각 (대상 바뀜 / 텔)
    stuck   = {'id': None, 'best': 0, 'pos': None, 't': 0.0}   #지금 대상에게 다가가고 있는지
    hpfail  = 0        #HP 를 연속으로 못 읽은 횟수
    atks    = [a for a in ATTACKS if a[0] != None and a[1] > 0]   #쓸 수 있는 공격 키만
    apress  = [0.0] * len(atks)      #공격 키를 마지막으로 누른 시각

    log('사냥 : 탐지 거리 ' + str(HUNT_DIST) + '타일, 가까운 순')
    for i, (akey, adelay, adist) in enumerate(atks):
        log('공격 키 ' + str(i + 1) + ' : ' + akey.upper() + '  딜레이 ' + str(adelay)
            + '초  거리 ' + str(adist) + '타일 이하')

    settrigger('hunt')
    while ALIVE:
        if runpending():       #버프/변신/귀환이 먼저 (공격 키보다 우선)
            continue

        found = scanents()
        if found == None:
            fail += 1
            if fail >= MEM_FAIL_LIMIT:
                log('엔티티 테이블을 ' + str(fail) + '번 연속 못 읽었다 - 정지')
                dostop()
                break
            time.sleep(HUNT_POLL)
            continue
        fail = 0

        now  = time.perf_counter()

        #힐 / 베르 : HP 가 정한 % 이하면 그 키를 누른다. 이뮨 : 주위 몹이 정한 수 이상이면 누른다
        #공격을 꺼 둬도 돈다. 감지만 모드에서는 키를 누르지 않는다
        if not DETECT_ONLY:
            if KEY_HEAL != None or KEY_BER != None:
                hpv = readhp()
                if hpv == None:
                    #HP 를 못 읽는데 계속 돌면 힐이 조용히 안 나간다. 연속으로 못 읽으면 멈춘다
                    hpfail += 1
                    if hpfail >= MEM_FAIL_LIMIT:
                        log('HP 를 ' + str(hpfail) + '번 연속 못 읽었다 (힐/베르 불가) - 정지')
                        dostop()
                        break
                else:
                    hpfail = 0
                    pct = hpv[0] * 100.0 / hpv[1]
                    if KEY_HEAL != None and pct <= HEAL_PCT and now - pressed['heal'] >= HEAL_GAP:
                        log('힐 ' + KEY_HEAL.upper() + '  (HP ' + str(hpv[0]) + '/' + str(hpv[1])
                            + ' = ' + str(int(pct)) + '% <= ' + str(HEAL_PCT) + '%)')
                        selfcast(KEY_HEAL, found['me'], '힐')      #내 캐릭터를 대상으로 시전
                        pressed['heal'] = now
                    if KEY_BER != None and pct <= BER_PCT and now - pressed['ber'] >= BER_GAP:
                        log('베르 ' + KEY_BER.upper() + '  (HP ' + str(int(pct)) + '% <= ' + str(BER_PCT) + '%)')
                        gu.press(KEY_BER, presses=1)
                        pressed['ber'] = now
                        #베르를 썼으면 매크로를 끝낸다 (피가 그만큼 빠진 것이므로 더 돌지 않는다)
                        log('베르 사용 - 정지')
                        dostop()
                        break
            if (KEY_IMMUNE != None and len(found['mobs']) >= IMMUNE_N
                    and now - pressed['immune'] >= IMMUNE_GAP):
                log('이뮨 ' + KEY_IMMUNE.upper() + '  (주위 몹 ' + str(len(found['mobs']))
                    + '마리 >= ' + str(IMMUNE_N) + ')')
                selfcast(KEY_IMMUNE, found['me'], '이뮨')        #내 캐릭터를 대상으로 시전
                pressed['immune'] = now

        #공격 끔 : 버프 / 변신 / 귀환 감시와 힐 / 베르 / 이뮨만 돈다
        #(예전의 수동 사냥 보조 - 대상 위에 커서를 올리면 휠 클릭 - 는 뺐다)
        # if win32gui.GetCursorInfo()[1] == atkvalue:
        #     gu.middleClick()
        if not ATTACK_ON and not DETECT_ONLY:
            time.sleep(HUNT_POLL)
            continue

        #화면 좌표를 미리 구해 화면 안에 있는 몹만 남긴다 (화면 밖은 클릭할 수 없다)
        #감지만 모드에서는 보정이 없을 수 있으므로 거르지 않는다
        mobs = []
        for dist, o, pos in found['mobs']:
            if skip.get(o['id'], 0) > now:
                continue      #다가가지 못해서 잠깐 빼 둔 몹 (벽 너머 등)
            xy = toscreen(pos[0] - found['pos'][0], pos[1] - found['pos'][1])
            if DETECT_ONLY or (xy != None and 0 <= xy[0] < screen[0] and 0 <= xy[1] < screen[1]):
                mobs.append((dist, o, pos, xy))

        #잡던 몹이 아직 살아 있는지. 목록에 없으면 죽었거나 사라졌거나 멀어진 것
        cur = None
        for r in mobs:
            if r[1]['id'] == target:
                cur = r
                break
        if cur == None:
            if target != None:
                log('대상 끝 : ' + tname)
            target  = None
            clicked = 0.0
            if len(mobs) > 0:
                cur = mobs[0]
        elif now - clicked >= RECLICK_SEC and mobs[0][0] < cur[0]:
            #클릭할 차례마다 서치를 갱신한다 : 잡던 몹보다 더 가까운 몹이 생겼으면 그쪽으로 바꾼다
            #(거리가 같으면 잡던 몹을 그대로 둔다. 안 그러면 두 몹 사이를 오락가락한다)
            cur = mobs[0]

        if cur == None:
            #주변에 잡을 몹이 없다 -> 기다리지 않고 바로 텔 (새로고침 키)
            #텔 직후에는 주변이 아직 안 읽혔을 수 있으므로 TELE_GAP 동안은 다시 누르지 않는다
            #(예전에는 NOHIT_LIMIT 회 헛돌 때까지 기다렸다)
            if KEY_REFRESH != None and (not DETECT_ONLY) and now - teled >= TELE_GAP:
                log('몹 없음 - 텔 : ' + KEY_REFRESH)
                time.sleep(TELE_DELAY)       #마지막 몹을 잡은 직후 바로 누르지 않고 잠깐 둔다
                gu.press(KEY_REFRESH, presses=1)
                teled = time.perf_counter()
                moved = teled
            time.sleep(HUNT_POLL)
            continue

        dist, o, pos, xy = cur
        if o['id'] != target:
            target  = o['id']
            tname   = str(o.get('name')) + ' (id ' + str(o['id']) + ')'
            clicked = 0.0
            moved   = now
            log(('[감지만] ' if DETECT_ONLY else '') + '대상 : ' + tname + '  거리 ' + str(dist)
                + '  남은 몹 ' + str(len(mobs)))

        if DETECT_ONLY:
            time.sleep(HUNT_POLL)
            continue

        #같은 대상을 잡은 채 한참 아무 변화가 없으면 (안 죽는 몹, 닿지 않는 몹) 강제로 텔한다
        #버프 로그는 변화로 치지 않는다 - 대상이 바뀌거나 텔한 것만 변화다
        if KEY_REFRESH != None and now - moved >= IDLE_TELE_SEC:
            log(str(int(IDLE_TELE_SEC)) + '초 동안 변화 없음 (' + tname + ') - 강제 텔 : ' + KEY_REFRESH)
            gu.press(KEY_REFRESH, presses=1)
            teled   = time.perf_counter()
            moved   = teled
            target  = None
            tname   = ''
            clicked = 0.0
            time.sleep(HUNT_POLL)
            continue

        #다가가고 있는지 본다. 내 좌표가 바뀌거나 거리가 줄면 진전이 있는 것
        if stuck['id'] != o['id']:
            stuck = {'id': o['id'], 'best': dist, 'pos': found['pos'], 't': now}
        elif dist < stuck['best'] or found['pos'] != stuck['pos']:
            stuck['best'] = min(stuck['best'], dist)
            stuck['pos']  = found['pos']
            stuck['t']    = now
        elif dist > STUCK_REACH and now - stuck['t'] >= STUCK_SEC:
            log('막힘 : ' + tname + '  거리 ' + str(dist) + ' 에서 ' + str(int(STUCK_SEC))
                + '초 동안 못 다가감 - ' + str(int(SKIP_SEC)) + '초 동안 제외')
            skip[o['id']] = now + SKIP_SEC
            target  = None
            tname   = ''
            clicked = 0.0
            continue

        if now - clicked >= RECLICK_SEC:
            #칼 모양 확인 없이 바로 클릭한다
            # _movefast(parkpos[0], parkpos[1])      #커서 모양 초기화
            # if _probe(xy[0], xy[1], atkvalue):
            #     _settleclick(xy[0], xy[1], atkvalue)
            if NATURAL_ON:
                _movehuman(xy[0] + random.randint(-CLICK_ADJ, CLICK_ADJ),
                           xy[1] + random.randint(-CLICK_ADJ, CLICK_ADJ))
                time.sleep(random.uniform(*CLICK_DELAY))
            else:
                _movefast(xy[0], xy[1])
            gu.click()
            clicked = time.perf_counter()

        #공격 키 : 대상과의 거리가 정한 값 이하이고 딜레이가 지났으면 누른다
        #한 바퀴에 하나만 누른다 (앞 번호가 먼저). 버프 / 변신 / 귀환은 바퀴 머리의 runpending 이 먼저 처리한다
        now = time.perf_counter()
        for i, (akey, adelay, adist) in enumerate(atks):
            if dist <= adist and now - apress[i] >= adelay:
                log('공격 키 ' + akey.upper() + '  (거리 ' + str(dist) + ' <= ' + str(adist) + ')')
                gu.press(akey, presses=1)
                apress[i] = time.perf_counter()
                break
        time.sleep(HUNT_POLL)

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
    for rid in ROLE_IDS:
        v = raw.get(rid)
        if rid == 'transform':
            #변신은 버프 페이지(F2) 의 키라 공격 페이지 역할과 겹쳐도 된다
            roles[rid] = v if v in FKEYS else None
            continue
        #같은 키가 두 역할에 겹치면 뒤엣것을 버린다
        roles[rid] = v if (v in FKEYS and v not in used) else None
        if roles[rid] != None:
            used.add(roles[rid])

    #공격 키. 역할과 겹치는 키, 앞 줄과 겹치는 키는 '안 씀' 으로 돌린다
    attacks = []
    rawatk  = data.get('attacks')
    if not isinstance(rawatk, list):
        #옛 설정 : roles.skill + 그 키의 주기 칸 -> 공격 키 1번
        old = raw.get('skill')
        if old in FKEYS and old not in used:
            rawatk = [{'key': old, 'delay': seconds.get(old, 0), 'dist': defaultattacks()[0]['dist']}]
        else:
            rawatk = defaultattacks()
    for item in rawatk[:ATTACK_MAX]:
        if not isinstance(item, dict):
            continue
        a = dict(defaultattacks()[0])
        key = item.get('key')
        a['key'] = key if (key in FKEYS and key not in used) else None
        if a['key'] != None:
            used.add(a['key'])
        try:
            v = float(item.get('delay', a['delay']))
            if v >= 0:
                a['delay'] = v
        except (TypeError, ValueError):
            pass
        try:
            v = int(item.get('dist', a['dist']))
            if v in DIST_CHOICES:
                a['dist'] = v
        except (TypeError, ValueError):
            pass
        attacks.append(a)
    if len(attacks) == 0:
        attacks = defaultattacks()
        attacks[0]['key'] = None
    opts['attacks'] = attacks

    #옵션은 아는 키만, 값이 이상하면 기본값을 유지한다
    if isinstance(data.get('attack'), bool):
        opts['attack'] = data['attack']
    if isinstance(data.get('sound'), bool):
        opts['sound'] = data['sound']
    if isinstance(data.get('detect'), bool):
        opts['detect'] = data['detect']
    try:
        v = int(data.get('dist', opts['dist']))
        if v >= 1:
            opts['dist'] = v
    except (TypeError, ValueError):
        pass
    gaps   = defaultgaps()
    rawgap = data.get('gaps')
    for rid in gaps:
        if isinstance(rawgap, dict):
            v = rawgap.get(rid, 0)
        else:
            #옛 설정 : 재사용 간격이 그 키의 주기 칸에 들어 있었다
            v = seconds.get(roles.get(rid), 0) if roles.get(rid) else 0
        try:
            v = int(v)
            gaps[rid] = v if v >= 0 else 0
        except (TypeError, ValueError):
            pass
    opts['gaps'] = gaps
    for key, lo, hi in (('heal_pct', 1, 99), ('ber_pct', 1, 99), ('immune_n', 1, 99)):
        try:
            v = int(data.get(key, opts[key]))
            if lo <= v <= hi:
                opts[key] = v
        except (TypeError, ValueError):
            pass
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
            'roles':   dict((rid, roles.get(rid)) for rid in ROLE_IDS),
            'attack':  bool(opts.get('attack', DEFAULT_OPTS['attack'])),
            'range':   str(opts.get('range',  DEFAULT_OPTS['range'])),
            'nohit':   int(opts.get('nohit',  DEFAULT_OPTS['nohit'])),
            'sound':   bool(opts.get('sound',  DEFAULT_OPTS['sound'])),
            'dist':    int(opts.get('dist',    DEFAULT_OPTS['dist'])),
            'detect':  bool(opts.get('detect', DEFAULT_OPTS['detect'])),
            'heal_pct': int(opts.get('heal_pct', DEFAULT_OPTS['heal_pct'])),
            'ber_pct':  int(opts.get('ber_pct',  DEFAULT_OPTS['ber_pct'])),
            'immune_n': int(opts.get('immune_n', DEFAULT_OPTS['immune_n'])),
            'gaps':     dict((rid, int((opts.get('gaps') or {}).get(rid, 0) or 0)) for rid in defaultgaps()),
            'attacks':  [{'key':   (a.get('key') if a.get('key') in FKEYS else None),
                          'delay': float(a.get('delay', 0)),
                          'dist':  int(a.get('dist', defaultattacks()[0]['dist']))}
                         for a in (opts.get('attacks') or defaultattacks())[:ATTACK_MAX]]}
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
    #seconds : {키 -> 초},  roles : {'return'/'refresh'/'transform'/'heal'/'immune'/'ber' -> 키 or None}
    #opts    : {'attack': bool, 'range': 'near'/'far', 'nohit': int, 'sound': bool, ..., 'attacks': [...]}
    global BUFFS, BUFFKEY, TRIGGER, ORDER, PENDING
    global KEY_RETURN, KEY_REFRESH, KEY_TRANSFORM, TRANSFORM_INTERVAL, KEY_SKILL, SKILL_COOL, ATTACKS
    global ATTACK_ON, SCAN_ROUND, NOHIT_LIMIT, SOUND_ON, HUNT_DIST, DETECT_ONLY
    global KEY_HEAL, KEY_BER, KEY_IMMUNE, HEAL_PCT, BER_PCT, IMMUNE_N, HEAL_GAP, BER_GAP, IMMUNE_GAP

    if opts == None:
        opts = dict(DEFAULT_OPTS)
    ATTACK_ON     = bool(opts.get('attack', DEFAULT_OPTS['attack']))
    SCAN_ROUND    = SCAN_FAR if opts.get('range') == 'far' else SCAN_NEAR
    NOHIT_LIMIT   = max(1, int(opts.get('nohit', DEFAULT_OPTS['nohit'])))
    SOUND_ON      = bool(opts.get('sound', DEFAULT_OPTS['sound']))
    HUNT_DIST     = max(1, int(opts.get('dist', DEFAULT_OPTS['dist'])))
    DETECT_ONLY   = bool(opts.get('detect', DEFAULT_OPTS['detect']))
    KEY_RETURN    = roles.get('return')
    KEY_REFRESH   = roles.get('refresh')
    KEY_TRANSFORM = roles.get('transform')

    #공격 키. 같은 페이지(F1) 의 역할 키와 겹치면 뺀다 (GUI 가 막지만 파일을 손으로 고쳤을 수 있다)
    taken   = set(roles.get(rid) for rid in PAGE_ROLES if roles.get(rid))
    ATTACKS = []
    for a in (opts.get('attacks') or defaultattacks())[:ATTACK_MAX]:
        key = a.get('key')
        if key in FKEYS and key not in taken:
            ATTACKS.append((key, float(a.get('delay', 0)), int(a.get('dist', defaultattacks()[0]['dist']))))
            taken.add(key)
    KEY_SKILL  = ATTACKS[0][0] if ATTACKS else None     #(호환) pit.py 용
    SKILL_COOL = ATTACKS[0][1] if ATTACKS else 0

    KEY_HEAL      = roles.get('heal')
    KEY_BER       = roles.get('ber')
    KEY_IMMUNE    = roles.get('immune')
    HEAL_PCT      = int(opts.get('heal_pct', DEFAULT_OPTS['heal_pct']))
    BER_PCT       = int(opts.get('ber_pct',  DEFAULT_OPTS['ber_pct']))
    IMMUNE_N      = int(opts.get('immune_n', DEFAULT_OPTS['immune_n']))
    #재사용 간격 = 그 키의 주기 칸. 0 이면 기본값
    #재사용 간격은 opts['gaps'] (버프 탭의 주기 칸과 별개). 0 이면 기본값
    gaps          = opts.get('gaps') or defaultgaps()
    HEAL_GAP      = float(gaps.get('heal', 0)   or GAP_DEFAULT['heal'])
    BER_GAP       = float(gaps.get('ber', 0)    or GAP_DEFAULT['ber'])
    IMMUNE_GAP    = float(gaps.get('immune', 0) or GAP_DEFAULT['immune'])

    TRANSFORM_INTERVAL = seconds.get(KEY_TRANSFORM, 0) if KEY_TRANSFORM else 0

    #버프는 버프 페이지(F2) 의 키라서 공격 페이지의 역할 / 공격 키와 겹쳐도 된다. 변신 키만 뺀다
    BUFFS = []
    for i, key in enumerate(FKEYS):
        if key == KEY_TRANSFORM:
            continue
        BUFFS.append(('buff' + str(i + 1), key, seconds.get(key, 0)))
    BUFFKEY = dict((n, key) for n, key, s in BUFFS)

    TRIGGER = {'hunt': False, 'stop': False, 'transform': False, 'return': False, 'chatbuff': False}
    for n, key, s in BUFFS:
        TRIGGER[n] = False
    ORDER = ['stop', 'return'] + [n for n, key, s in BUFFS] + ['transform', 'chatbuff']   #채팅버프는 맨 뒤 (채팅 뒤의 키가 씹힌다)
    with PENDING_LOCK:
        PENDING = {}

#매크로 본체. GUI 스레드가 아니라 전용 스레드에서 돈다
#끝나면(정지/오류) GUI 가 스레드 종료를 보고 시작 버튼을 다시 켠다
def runmacro():
    global ALIVE, HOTKEY, HUNT_START, MEM, CALIB, WATCH_FAIL, WATCH_SEEN, CASTER
    expstart   = None    #사냥을 시작할 때의 (레벨, 경험치, %)
    adenastart = None    #사냥을 시작할 때의 아데나
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

        #메모리에 붙는다. 못 붙거나 필요한 값이 없으면 시작하지 않는다 (화면 방식으로 넘어가지 않는다)
        WATCH_FAIL = 0
        WATCH_SEEN = set()
        path, okay, tried = mr.findfile('mem.json')
        MEM = mr.Mem(path, log)
        if not MEM.attach():
            log('메모리 붙기 실패 : ' + str(MEM.err))
            return
        if KEY_HEAL != None or KEY_IMMUNE != None:
            import memcast                  #대상 id 쓰기 + 키 누르기 + 되돌리기
            CASTER = memcast.Caster(MEM)
        kinds = MEM.entkinds()
        first = scanents()
        if first == None:
            log('엔티티 테이블에서 내 캐릭터를 못 찾았다 (python memprobe.py --entkind 로 확인) - 시작 안 함')
            return
        log('내 캐릭터 : ' + str(first['me'].get('name')) + '  좌표 ' + str(first['pos'])
            + '  종류 규칙 : ' + (', '.join(sorted(kinds)) if kinds else '없음'))
        if 'monster' not in kinds:
            log('monster 규칙 없음 - 캐릭터가 아닌 것(이름 있는 것)을 전부 대상으로 본다. NPC 도 클릭될 수 있다')
        if DETECT_ONLY:
            log('감지만 - 클릭/귀환/새로고침을 하지 않고 로그만 찍습니다')

        atk = None
        if ATTACK_ON and not DETECT_ONLY:
            CALIB, why = loadcalib()
            if CALIB == None:
                log('화면 보정이 없어 몹을 클릭할 수 없다 : ' + why)
                log('postracker.py 에서 허수아비 보정(F9)을 3점 이상 찍은 뒤 다시 시작 - 시작 안 함')
                return
            log('화면 보정 : ' + why)
            #공격 커서(칼 모양)는 더 이상 확인하지 않으므로 캡처도 하지 않는다
            # atk = setattckinfo(CENTERPOINT)
            # log('공격 커서 : ' + str(atk))
        elif not ATTACK_ON:
            log('공격 끔 - 버프 / 변신 / 힐 / 베르 / 이뮨만 돕니다')

        if KEY_TRANSFORM != None and TRANSFORM_INTERVAL > 0:
            log('변신(' + KEY_TRANSFORM + ') ' + str(TRANSFORM_INTERVAL) + '초 주기')
            transformtimer()
        else:
            log('변신 미지정 - 변신 끔')

        startbuffs()

        log('채팅버프(' + CHAT_CMD + ') ' + str(CHAT_INTERVAL) + '초 주기')
        chatbufftimer()

        #귀환 역할은 뺐다 (KEY_RETURN 은 항상 None). 주변 캐릭터 감시는 감지만 모드에서 로그만 찍는다
        if KEY_RETURN != None or DETECT_ONLY:
            if 'player' not in kinds:
                log('mem.json ent.rules 에 player 규칙이 없어 주변 캐릭터를 가릴 수 없다 - 시작 안 함')
                return
            log('피 / 주변 캐릭터 감시 시작 (로그만)')
            checkrHp()

        if KEY_REFRESH == None:
            log('새로고침키 미지정 - 새로고침 끔')

        #소리 감시는 쓰지 않는다. 몹이 살아 있는지는 엔티티 테이블로 안다
        # if SOUND_ON:
        #     t = threading.Thread(target=soundwatch)
        #     t.daemon = True
        #     t.start()

        HUNT_START = time.time()
        expstart   = readexp()     #끝날 때 얼마나 올랐는지 찍으려고 잡아 둔다
        adenastart = readadena()
        #시작 순서 : 버프 / 변신 요청이 쌓여 있으면 사냥 루프 첫 바퀴의 runpending 이 F2 -> 전부 누름 -> F1 로 처리한다
        #쌓인 것이 없어도 공격 페이지에서 시작하도록 F1 을 한 번 누른다 (감지만 모드에서는 키를 안 누른다)
        if not DETECT_ONLY:
            setpage(PAGE_ATTACK)
        log('사냥 시작')
        huntloop([CENTERPOINT[0], CENTERPOINT[1] + SCAN_OFFSET_Y], atk)
    except Exception as e:
        log('매크로 오류 : ' + str(e))
        log(traceback.format_exc())      #어디서 터졌는지 알아야 고친다
    finally:
        #정지든 오류든 여기로 온다. 타이머와 핫키를 반드시 걷어낸다
        ALIVE = False
        canceltimers()
        #피 소모 귀환이든 tab 정지든, 사냥이 얼마나 돌았는지 남긴다
        if HUNT_START != None:
            log('사냥 시간 : ' + fmtsec(time.time() - HUNT_START)
                + ' (' + time.strftime('%H:%M:%S', time.localtime(HUNT_START)) + ' 시작)')
            try:
                log(fmtexp(expstart, readexp()))      #사냥하는 동안 오른 경험치
            except Exception as e:
                log('경험치 : 못 읽음 (' + str(e) + ')')
            try:
                log(fmtadena(adenastart, readadena()))   #사냥하는 동안 늘어난 아데나
            except Exception as e:
                log('아데나 : 못 읽음 (' + str(e) + ')')
            HUNT_START = None
        else:
            log('사냥 시작 전 종료')
        if HOTKEY != None:
            try:
                k.remove_hotkey(HOTKEY)
            except Exception:
                pass
            HOTKEY = None
        if CASTER != None:
            CASTER.close()
            CASTER = None
        if MEM != None:
            MEM.detach()
            MEM = None
        CALIB = None
        settrigger(None)
        log('매크로 종료')

#=====================================================================
# GUI
#=====================================================================
ROLES = [('refresh', '새로고침'), ('heal', '힐'), ('immune', '이뮨'), ('ber', '베르')]   #공격 탭의 역할 (F1 페이지)
NOTE_COL = 2                #버프 표에서 주기 다음 칸 = 설명
KEY_NONE = '없음'            #키 드롭다운의 '안 씀'
ROLE_HINT = {'refresh': '주변에 몹이 없으면 바로 (텔)'}
KEY_CHOICES = [KEY_NONE] + [key.upper() for key in FKEYS]

class App:
    def __init__(self, root):
        self.root    = root
        self.started = False
        self.sec     = {}    #키 -> StringVar (주기)
        self.entry   = {}    #키 -> Entry
        self.note    = {}    #키 -> Label (주기 설명)
        self.rolekey = {}    #역할 -> StringVar (KEY_NONE 또는 'F5'..'F12')  공격 탭
        self.rolesec = {}    #역할 -> StringVar (재사용 간격, opts['gaps']).  버프 탭의 주기 칸과 별개
        self.transkey = tk.StringVar(value=KEY_NONE)   #변신 키 (버프 탭, F2 페이지). 주기는 그 키의 주기 칸
        self.rolewid = {}    #역할 -> 잠글 위젯들
        self.thread  = None  #매크로 스레드. 끝나면 UI 를 다시 연다
        self.atkkey   = []   #공격 줄 -> StringVar (KEY_NONE 또는 'F5'..'F12')
        self.atkdelay = []   #공격 줄 -> StringVar (딜레이 초)
        self.atkdist  = []   #공격 줄 -> StringVar (몹과의 거리 타일)
        self.atkwid   = []   #공격 줄 -> (키 콤보, 딜레이 Entry, 거리 콤보)
        self.atkrow   = []   #공격 줄 -> 그 줄의 위젯들 (보이기/숨기기용)
        self.atkn     = 1    #보이는 공격 줄 수 (기본 한 개)

        root.title('사냥 매크로')
        root.protocol('WM_DELETE_WINDOW', lambda: os._exit(0))

        #--- 탭 : 메인 / 버프 / 공격 ---
        #설정 저장 / 시작 버튼 / 로그는 탭 밖(아래)에 둬서 어느 탭에서나 보인다
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill='x', padx=10, pady=(10, 0))
        maintab = ttk.Frame(self.nb)
        bufftab = ttk.Frame(self.nb)
        atktab  = ttk.Frame(self.nb)
        self.nb.add(maintab, text='  메인  ')
        self.nb.add(bufftab, text='  버프  ')
        self.nb.add(atktab,  text='  공격  ')

        #--- 내 캐릭터 정보 (실시간) ---
        #매크로가 안 돌 때도 보이도록 GUI 가 읽기 전용으로 따로 붙어서 읽는다
        infobox = ttk.LabelFrame(maintab, text='내 캐릭터')
        infobox.pack(fill='x', padx=10, pady=(10, 0))
        self.infovar = tk.StringVar(value='게임에 붙는 중...')
        ttk.Label(infobox, textvariable=self.infovar, justify='left',
                  font=('Consolas', 10)).pack(anchor='w', padx=8, pady=6)
        self.imem   = None    #정보 표시용 memread.Mem (매크로의 MEM 과 별개)
        self.iretry = 0       #다시 붙기까지 남은 갱신 횟수
        self.ifail  = 0       #연속으로 못 읽은 횟수

        #--- 키 설정 표 (버프 탭) ---
        box = ttk.LabelFrame(bufftab, text='버프 키 설정 (f5 ~ f12, 단축키 페이지 F2)')
        box.pack(fill='x', padx=10, pady=(10, 4))

        ttk.Label(box, text='키',      width=6,  anchor='center').grid(row=0, column=0, padx=4, pady=4)
        ttk.Label(box, text='주기(초)', width=10, anchor='center').grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(box, text='', width=24).grid(row=0, column=NOTE_COL, padx=4)

        for r, key in enumerate(FKEYS, start=1):
            ttk.Label(box, text=key.upper(), width=6, anchor='center').grid(row=r, column=0, padx=4, pady=2)

            var = tk.StringVar(value='0')
            self.sec[key] = var
            ent = ttk.Entry(box, textvariable=var, width=10, justify='center')
            ent.grid(row=r, column=1, padx=4, pady=2)
            self.entry[key] = ent

            nl = ttk.Label(box, text='버프 주기', width=24, foreground='#555')
            nl.grid(row=r, column=NOTE_COL, padx=4, pady=2, sticky='w')
            self.note[key] = nl

        trow = ttk.Frame(bufftab)
        trow.pack(fill='x', padx=14, pady=(2, 0))
        ttk.Label(trow, text='변신 키').pack(side='left')
        self.transbox = ttk.Combobox(trow, textvariable=self.transkey, width=6, state='readonly',
                                     values=KEY_CHOICES)
        self.transbox.pack(side='left', padx=(6, 0))
        self.transbox.bind('<<ComboboxSelected>>', lambda e: self.refreshrows())
        ttk.Label(trow, foreground='#555',
                  text='  변신은 위 표의 그 키 주기마다. 변신 메뉴(lv80 / night)를 화면에서 찾아 누릅니다'
                  ).pack(side='left')
        ttk.Label(bufftab, foreground='#555',
                  text='버프 탭의 키는 단축키 페이지 F2 의 칸입니다. 주기(초)마다 F2 -> 키 -> F1 순으로 누릅니다. 0 이면 안 씁니다.\n'
                       '시작할 때도 F2 로 바꿔 주기가 있는 버프를 전부 건 뒤 F1 로 돌아와 사냥합니다.\n'
                       '공격 탭(F1 페이지)과는 다른 칸이라 같은 F 키를 양쪽에 써도 됩니다.'
                  ).pack(anchor='w', padx=12, pady=(4, 8))

        #--- 공격 키 (공격 탭) ---
        self._buildattack(atktab)

        #--- 동작 설정 (메인 탭) ---
        optbox = ttk.LabelFrame(maintab, text='동작')
        optbox.pack(fill='x', padx=10, pady=(8, 10))
        self.attack = tk.BooleanVar(value=DEFAULT_OPTS['attack'])
        self.atkchk = ttk.Checkbutton(optbox, text='공격 사용 (가까운 몹부터 클릭)',
                                      variable=self.attack)
        self.atkchk.pack(anchor='w', padx=6, pady=4)
        ttk.Label(optbox, foreground='#555',
                  text='몹 위치를 메모리에서 읽어 가장 가까운 몹을 클릭하고, 죽으면 다음으로 가까운 몹으로 넘어갑니다.\n'
                       '끄면 클릭하지 않고 버프 / 변신 / 피·주변 캐릭터 감시만 돕니다.'
                  ).pack(anchor='w', padx=6, pady=(0, 4))

        #--- 탐지 거리(타일) / 감지만 ---
        dsrow = ttk.Frame(optbox)
        dsrow.pack(fill='x', padx=6, pady=(2, 0))
        ttk.Label(dsrow, text='탐지 거리', width=12).pack(side='left')
        self.dist  = tk.StringVar(value=str(DEFAULT_OPTS['dist']))
        self.dsent = ttk.Entry(dsrow, textvariable=self.dist, width=6, justify='center')
        self.dsent.pack(side='left')
        ttk.Label(dsrow, foreground='#555', text='  타일 안의 몹만 대상으로 삼습니다').pack(side='left')
        self.detect = tk.BooleanVar(value=DEFAULT_OPTS['detect'])
        self.dtchk  = ttk.Checkbutton(optbox, text='감지만 (클릭 / 귀환 없이 로그만 - 확인용)',
                                      variable=self.detect)
        self.dtchk.pack(anchor='w', padx=6, pady=(4, 0))

        #--- 칼 탐지 거리 ---
        rngrow = ttk.Frame(optbox)
        rngrow.pack(fill='x', padx=6, pady=(6, 0))
        ttk.Label(rngrow, text='(예전) 서치 거리', width=12).pack(side='left')
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
        ttk.Label(nhrow, text='(예전) 헛돔 횟수', width=12).pack(side='left')
        self.nohit = tk.StringVar(value=str(DEFAULT_OPTS['nohit']))
        self.nhent = ttk.Entry(nhrow, textvariable=self.nohit, width=6, justify='center')
        self.nhent.pack(side='left')
        ttk.Label(nhrow, foreground='#555',
                  text='  지금은 쓰지 않음 - 주변에 몹이 없으면 바로 새로고침(텔) 키를 누릅니다'
                  ).pack(side='left')

        #--- 소리 감지 ---
        self.sound  = tk.BooleanVar(value=DEFAULT_OPTS['sound'])
        self.sndchk = ttk.Checkbutton(optbox, text='(예전) 소리로 칼질 감지 - 지금 사냥에서는 쓰지 않음',
                                      variable=self.sound)
        self.sndchk.pack(anchor='w', padx=6, pady=(6, 0))
        ttk.Label(optbox, foreground='#555',
                  text='스피커로 나가는 소리를 듣고 칼질중이면 마우스 서치를 멈췄다가, '
                       '소리가 끊기면 멈춘 자리에서 이어서 돕니다.\n'
                       'PyAudioWPatch 가 필요하고, 게임 BGM 을 끄면 판정이 정확해집니다. '
                       '장치를 못 열면 자동으로 꺼지고 예전처럼 계속 서치합니다.'
                  ).pack(anchor='w', padx=6, pady=(0, 4))

        #--- 저장 / 불러오기 / 기본값 (탭 아래, 모든 탭 공통) ---
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
        self.pollinfo()
        log(('설정 불러옴 : ' + CONFIG_PATH) if found else '저장된 설정 없음 - 기본 셋팅 사용')

    #--- 공격 탭 ---

    #공격 키 표. ATTACK_MAX 줄을 다 만들어 두고 atkn 개만 보인다
    def _buildattack(self, parent):
        box = ttk.LabelFrame(parent, text='공격 키 (최대 %d개, 단축키 페이지 F1)' % ATTACK_MAX)
        box.pack(fill='x', padx=10, pady=(10, 4))

        ttk.Label(box, text='번호',  width=6,  anchor='center').grid(row=0, column=0, padx=4, pady=4)
        ttk.Label(box, text='키',    width=8,  anchor='center').grid(row=0, column=1, padx=4, pady=4)
        ttk.Label(box, text='딜레이(초)', width=10, anchor='center').grid(row=0, column=2, padx=4, pady=4)
        ttk.Label(box, text='몹과의 거리(타일)', width=16, anchor='center').grid(row=0, column=3, padx=4, pady=4)

        d0 = defaultattacks()[0]
        for i in range(ATTACK_MAX):
            kv = tk.StringVar(value=KEY_NONE)
            dv = tk.StringVar(value=str(d0['delay']))
            sv = tk.StringVar(value=str(d0['dist']))
            self.atkkey.append(kv)
            self.atkdelay.append(dv)
            self.atkdist.append(sv)

            num = ttk.Label(box, text=str(i + 1), width=6, anchor='center')
            num.grid(row=i + 1, column=0, padx=4, pady=2)
            kb = ttk.Combobox(box, textvariable=kv, width=6, state='readonly', values=KEY_CHOICES)
            kb.grid(row=i + 1, column=1, padx=4, pady=2)
            kb.bind('<<ComboboxSelected>>', lambda e, ii=i: self.onatkkey(ii))
            de = ttk.Entry(box, textvariable=dv, width=10, justify='center')
            de.grid(row=i + 1, column=2, padx=4, pady=2)
            sb = ttk.Combobox(box, textvariable=sv, width=6, state='readonly',
                              values=[str(v) for v in DIST_CHOICES])
            sb.grid(row=i + 1, column=3, padx=4, pady=2)
            self.atkwid.append((kb, de, sb))
            self.atkrow.append((num, kb, de, sb))

        btnrow = ttk.Frame(box)
        btnrow.grid(row=ATTACK_MAX + 1, column=0, columnspan=4, sticky='w', padx=4, pady=(4, 6))
        self.atkadd = ttk.Button(btnrow, text='+ 추가', width=8, command=self.onatkadd)
        self.atkdel = ttk.Button(btnrow, text='- 제거', width=8, command=self.onatkdel)
        self.atkadd.pack(side='left', padx=(0, 4))
        self.atkdel.pack(side='left')

        ttk.Label(parent, foreground='#555',
                  text='대상을 클릭한 뒤, 대상과의 거리가 정한 타일 이하이고 딜레이가 지났으면 그 키를 누릅니다.\n'
                       '버프 / 변신 / 귀환 / 채팅버프가 먼저 처리된 뒤에 눌리고, 윗줄이 먼저입니다. 딜레이 0 은 안 씀.'
                  ).pack(anchor='w', padx=12, pady=(0, 4))
        self.showatk()

        #--- 역할 키 : 귀환 / 새로고침 / 변신 / 힐 / 이뮨 / 베르 ---
        rbox = ttk.LabelFrame(parent, text='역할 키 (단축키 페이지 F1)')
        rbox.pack(fill='x', padx=10, pady=(4, 4))
        self.healpct = tk.StringVar(value=str(DEFAULT_OPTS['heal_pct']))
        self.berpct  = tk.StringVar(value=str(DEFAULT_OPTS['ber_pct']))
        self.immunen = tk.StringVar(value=str(DEFAULT_OPTS['immune_n']))
        for r, (rid, label) in enumerate(ROLES):
            kv = tk.StringVar(value=KEY_NONE)
            self.rolekey[rid] = kv
            ttk.Label(rbox, text=label, width=8, anchor='e').grid(row=r, column=0, padx=4, pady=2, sticky='e')
            kb = ttk.Combobox(rbox, textvariable=kv, width=6, state='readonly', values=KEY_CHOICES)
            kb.grid(row=r, column=1, padx=4, pady=2)
            kb.bind('<<ComboboxSelected>>', lambda e, rr=rid: self.onrolekey(rr))
            wids = [kb]
            extra = ttk.Frame(rbox)
            extra.grid(row=r, column=2, padx=4, pady=2, sticky='w')
            if rid in ROLE_HINT:
                ttk.Label(extra, text=ROLE_HINT[rid], foreground='#555').pack(side='left')
            else:
                if rid == 'heal' or rid == 'ber':
                    var = self.healpct if rid == 'heal' else self.berpct
                    ttk.Label(extra, text='HP').pack(side='left')
                    cb = ttk.Combobox(extra, textvariable=var, width=4, state='readonly',
                                      values=[str(v) for v in PCT_CHOICES])
                    cb.pack(side='left', padx=(4, 0))
                    ttk.Label(extra, text='% 이하').pack(side='left', padx=(2, 10))
                    wids.append(cb)
                elif rid == 'immune':
                    ttk.Label(extra, text='주위 몹').pack(side='left')
                    cb = ttk.Combobox(extra, textvariable=self.immunen, width=4, state='readonly',
                                      values=[str(v) for v in MOB_CHOICES])
                    cb.pack(side='left', padx=(4, 0))
                    ttk.Label(extra, text='마리 이상').pack(side='left', padx=(2, 10))
                    wids.append(cb)
                sv = tk.StringVar(value='0')
                self.rolesec[rid] = sv
                ttk.Label(extra, text='재사용 간격').pack(side='left')
                se = ttk.Entry(extra, textvariable=sv, width=7, justify='center')
                se.pack(side='left', padx=(4, 0))
                ttk.Label(extra, text='초  (0 = %d초)' % GAP_DEFAULT[rid],
                          foreground='#555').pack(side='left', padx=(2, 0))
                wids.append(se)
            self.rolewid[rid] = wids
        ttk.Label(parent, foreground='#555',
                  text='역할은 각각 키 하나에만, 공격 키와도 겹치지 않게 지정됩니다 (같은 F1 페이지).\n'
                       '힐 / 이뮨은 내 캐릭터를 대상으로 시전하고, 주위 몹은 탐지 거리 안의 살아 있는 몹 수입니다.'
                  ).pack(anchor='w', padx=12, pady=(0, 8))

    #atkn 개의 줄만 보이게 한다
    def showatk(self):
        for i, row in enumerate(self.atkrow):
            for w in row:
                if i < self.atkn:
                    w.grid()
                else:
                    w.grid_remove()
        self.atkadd.configure(state='normal' if self.atkn < ATTACK_MAX else 'disabled')
        self.atkdel.configure(state='normal' if self.atkn > 1 else 'disabled')

    def onatkadd(self):
        if self.atkn < ATTACK_MAX:
            self.atkn += 1
            self.showatk()

    def onatkdel(self):
        if self.atkn > 1:
            self.atkn -= 1
            self.atkkey[self.atkn].set(KEY_NONE)      #숨긴 줄은 안 쓰는 것으로
            self.showatk()
            self.refreshrows()

    #i 번째 공격 줄의 키 (소문자) 또는 None
    def atkkeyof(self, i):
        v = self.atkkey[i].get()
        return v.lower() if (i < self.atkn and v != KEY_NONE) else None

    #key 를 쓰는 공격 줄 번호(1부터) 또는 None
    def atkrowof(self, key):
        for i in range(self.atkn):
            if self.atkkeyof(i) == key:
                return i + 1
        return None

    #공격 줄의 키가 바뀌면 같은 키를 쓰는 다른 줄과 버프 탭의 역할을 푼다
    def onatkkey(self, i):
        key = self.atkkeyof(i)
        if key != None:
            for j in range(ATTACK_MAX):
                if j != i and self.atkkey[j].get().lower() == key:
                    self.atkkey[j].set(KEY_NONE)
            for rid, label in ROLES:
                if self.rolekey[rid].get().lower() == key:
                    self.rolekey[rid].set(KEY_NONE)
        self.refreshrows()

    #역할 키가 바뀌면 같은 키를 쓰는 다른 역할과 공격 줄을 푼다
    def onrolekey(self, rid):
        v = self.rolekey[rid].get()
        if v != KEY_NONE:
            for orid, label in ROLES:
                if orid != rid and self.rolekey[orid].get() == v:
                    self.rolekey[orid].set(KEY_NONE)
            for i in range(ATTACK_MAX):
                if self.atkkey[i].get() == v:
                    self.atkkey[i].set(KEY_NONE)
        self.refreshrows()

    #--- 내 캐릭터 정보 ---

    #INFO_POLL 마다 캐릭터 정보를 읽어 표시한다. GUI 스레드에서 돌고 메모리는 읽기만 한다
    def pollinfo(self):
        try:
            self.infovar.set(self.readinfo())
        except Exception as e:
            self.infovar.set('정보 읽기 오류 : ' + str(e))
        self.root.after(INFO_POLL, self.pollinfo)

    #표시할 글자를 만든다. 못 붙었으면 몇 초마다 다시 붙어 본다
    def readinfo(self):
        if self.imem == None:
            if self.iretry > 0:
                self.iretry -= 1
                return '게임을 찾는 중... (Lin.exe 가 떠 있어야 합니다)'
            self.iretry = 6          #약 3초 뒤 다시 시도
            path, okay, tried = mr.findfile('mem.json')
            m = mr.Mem(path, lambda msg: None)     #붙었다는 로그는 찍지 않는다
            if not m.attach():
                return '게임에 못 붙음 : ' + str(m.err)
            self.imem  = m
            self.ifail = 0
        m = self.imem
        c = m.charinfo()
        if c == None or c.get('level') == None or c.get('hp_max') in (None, 0):
            #게임이 꺼졌거나 캐릭터 선택 화면이다. 계속 못 읽으면 떼고 다시 붙는다
            self.ifail += 1
            if self.ifail >= 6:
                m.detach()
                self.imem = None
            return '캐릭터 정보를 못 읽음 (월드에 들어가 있어야 합니다)'
        self.ifail = 0
        def f(v):
            return '?' if v == None else str(v)
        def pct(a, b):
            return '?' if (a == None or not b) else str(int(a * 100 / b))
        name = '?'
        pos  = '?'
        mobs = '?'
        ppl  = '?'
        ents, head, count = m.entity_table()
        me = m.selfent(ents) if len(ents) > 0 else None
        if me != None:
            name = str(me.get('name'))
            mp_  = m.entpos(me)
            pos  = str(mp_[0]) + ', ' + str(mp_[1])
            nm = 0
            np_ = 0
            for o in ents:
                if o['ptr'] == me['ptr']:
                    continue
                kind = m.kind(o)
                op = m.entpos(o)
                if kind == 'player':
                    np_ += 1
                elif (kind in ('other', 'monster') and not o['dead'] and o.get('name')
                      and max(abs(op[0] - mp_[0]), abs(op[1] - mp_[1])) <= HUNT_DIST):
                    nm += 1
            mobs = str(nm)
            ppl  = str(np_)
        return ('%s   LV %s   경험치 %s%%   AC %s\n'
                'HP %s / %s (%s%%)    MP %s / %s (%s%%)\n'
                '좌표 %s    주위 몹 %s    다른 캐릭터 %s'
                % (name, f(c['level']), f(c['exp_pct']), f(c['ac']),
                   f(c['hp']), f(c['hp_max']), pct(c['hp'], c['hp_max']),
                   f(c['mp']), f(c['mp_max']), pct(c['mp'], c['mp_max']),
                   pos, mobs, ppl))

    #--- 폼 <-> 값 ---

    #값을 위젯에 넣는다
    def setform(self, seconds, roles, opts):
        for key in FKEYS:
            self.sec[key].set(str(seconds.get(key, 0)))
        for rid, label in ROLES:
            key = roles.get(rid)
            self.rolekey[rid].set(key.upper() if key in FKEYS else KEY_NONE)
            if rid in self.rolesec:
                self.rolesec[rid].set(str((opts.get('gaps') or {}).get(rid, 0)))
        tkey = roles.get('transform')
        self.transkey.set(tkey.upper() if tkey in FKEYS else KEY_NONE)
        self.attack.set(bool(opts.get('attack', DEFAULT_OPTS['attack'])))
        self.range.set(str(opts.get('range',  DEFAULT_OPTS['range'])))
        self.nohit.set(str(opts.get('nohit',  DEFAULT_OPTS['nohit'])))
        self.sound.set(bool(opts.get('sound',  DEFAULT_OPTS['sound'])))
        self.dist.set(str(opts.get('dist',     DEFAULT_OPTS['dist'])))
        self.detect.set(bool(opts.get('detect', DEFAULT_OPTS['detect'])))
        self.healpct.set(str(opts.get('heal_pct', DEFAULT_OPTS['heal_pct'])))
        self.berpct.set(str(opts.get('ber_pct',   DEFAULT_OPTS['ber_pct'])))
        self.immunen.set(str(opts.get('immune_n', DEFAULT_OPTS['immune_n'])))
        attacks = (opts.get('attacks') or defaultattacks())[:ATTACK_MAX]
        d0 = defaultattacks()[0]
        self.atkn = max(1, len(attacks))
        for i in range(ATTACK_MAX):
            a = attacks[i] if i < len(attacks) else {}
            key = a.get('key')
            self.atkkey[i].set(key.upper() if key in FKEYS else KEY_NONE)
            delay = a.get('delay', d0['delay'])
            self.atkdelay[i].set(str(int(delay)) if float(delay) == int(delay) else str(delay))
            self.atkdist[i].set(str(a.get('dist', d0['dist'])))
        self.showatk()
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

        rawdist = self.dist.get().strip()
        if not rawdist.isdigit() or int(rawdist) < 1:
            log('탐지 거리는 1 이상 정수만 : ' + rawdist)
            return None, None, None

        roles = {}
        gaps  = defaultgaps()
        for rid, label in ROLES:
            v = self.rolekey[rid].get()
            roles[rid] = v.lower() if v in KEY_CHOICES and v != KEY_NONE else None
            if rid in self.rolesec:
                #재사용 간격은 따로 저장한다 (예전처럼 그 키의 주기 칸에 넣으면 같은 F 키의 버프 주기를 지워 버린다)
                raw = self.rolesec[rid].get().strip() or '0'
                if not raw.isdigit():
                    log(label + ' 재사용 간격은 0 이상 정수만 : ' + raw)
                    return None, None, None
                gaps[rid] = int(raw)
        v = self.transkey.get()
        roles['transform'] = v.lower() if v in KEY_CHOICES and v != KEY_NONE else None

        attacks = []
        for i in range(self.atkn):
            rawd = self.atkdelay[i].get().strip()
            try:
                delay = float(rawd) if rawd != '' else 0.0
                if delay < 0:
                    raise ValueError
            except ValueError:
                log('공격 키 ' + str(i + 1) + ' 딜레이는 0 이상 숫자만 : ' + rawd)
                return None, None, None
            attacks.append({'key': self.atkkeyof(i), 'delay': delay, 'dist': int(self.atkdist[i].get())})

        opts = {'attack': self.attack.get(),
                'range':  self.range.get(),
                'nohit':  int(raw),
                'sound':  self.sound.get(),
                'dist':   int(rawdist),
                'detect': self.detect.get(),
                'heal_pct': int(self.healpct.get()),
                'ber_pct':  int(self.berpct.get()),
                'immune_n': int(self.immunen.get()),
                'gaps':     gaps,
                'attacks':  attacks}
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

    #key 를 쓰는 역할 또는 None
    def roleof(self, key):
        for rid, label in ROLES:
            if self.rolekey[rid].get().lower() == key:
                return rid
        return None

    #버프 표의 설명 칸. 변신 키로 고른 줄은 '변신 주기'. 공격 탭(F1 페이지)과는 별개라 잠그지 않는다
    def refreshrows(self):
        for key in FKEYS:
            if self.transkey.get().lower() == key:
                self.entry[key].configure(state='normal')
                self.note[key].configure(text='변신 주기')
            else:
                self.entry[key].configure(state='normal')
                self.note[key].configure(text='버프 주기')

    def lockui(self):
        for key in FKEYS:
            self.entry[key].configure(state='disabled')
        for b in (self.savebtn, self.loadbtn, self.defbtn, self.atkchk, self.nhent, self.dsent, self.dtchk) + tuple(self.rngbtn):
            b.configure(state='disabled')
        for rid, wids in self.rolewid.items():
            for w in wids:
                w.configure(state='disabled')
        self.transbox.configure(state='disabled')
        for kb, de, sb in self.atkwid:
            kb.configure(state='disabled')
            de.configure(state='disabled')
            sb.configure(state='disabled')
        self.atkadd.configure(state='disabled')
        self.atkdel.configure(state='disabled')
        self.btn.configure(state='disabled', text='동작 중  (tab = 정지)')

    #정지하면 설정을 다시 만질 수 있게 열어준다
    def unlockui(self):
        for b in (self.savebtn, self.loadbtn, self.defbtn, self.atkchk, self.nhent, self.dsent, self.dtchk) + tuple(self.rngbtn):
            b.configure(state='normal')
        for rid, wids in self.rolewid.items():
            for w in wids:
                w.configure(state='readonly' if isinstance(w, ttk.Combobox) else 'normal')
        self.transbox.configure(state='readonly')
        for kb, de, sb in self.atkwid:
            kb.configure(state='readonly')
            de.configure(state='normal')
            sb.configure(state='readonly')
        self.showatk()          #추가 / 제거 버튼은 줄 수에 따라
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
        log('  탐지 거리 : ' + str(opts['dist']) + '타일' + ('  (감지만)' if opts.get('detect') else ''))
        log('  새로고침(텔) : 주변에 몹이 없으면 바로')
        log('  힐 : ' + ((roles['heal'].upper() + '  HP ' + str(opts['heal_pct']) + '% 이하') if roles.get('heal') else '미지정'))
        log('  베르 : ' + ((roles['ber'].upper() + '  HP ' + str(opts['ber_pct']) + '% 이하') if roles.get('ber') else '미지정'))
        log('  이뮨 : ' + ((roles['immune'].upper() + '  주위 몹 ' + str(opts['immune_n']) + '마리 이상') if roles.get('immune') else '미지정'))
        for rid, label in ROLES:
            log('  ' + label + ' : ' + (roles[rid].upper() if roles[rid] else '미지정'))
        log('  변신 (F2 페이지) : ' + ((roles['transform'].upper() + '  ' + str(seconds.get(roles['transform'], 0)) + '초 주기')
                                    if roles.get('transform') else '미지정'))
        for i, a in enumerate(opts.get('attacks') or []):
            log('  공격 키 ' + str(i + 1) + ' : '
                + ((a['key'].upper() + '  딜레이 ' + str(a['delay']) + '초  거리 ' + str(a['dist']) + '타일 이하')
                   if a.get('key') else '미지정'))
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
