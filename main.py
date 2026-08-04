import time
import win32gui
import win32api
import pyautogui as gu
import schedule as sc
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
print('이미지 경로: ' + IMAGE_DIR)

#최신 pyautogui 는 이미지 못 찾으면 None 대신 ImageNotFoundException 을 던짐
#아래 코드 전체가 None 비교를 전제로 하므로 예전 동작(None 반환)으로 되돌림
gu.useImageNotFoundException(False)

ishunting =0
isture=True

#탐색 튜닝값 (실기에서 조정)
PROBE_SETTLE = 0.025   # 커서 모양 갱신 대기 최대치(초)
PROBE_STEP   = 0.003   # 폴링 간격(초)
CTRL_DELAY   = 0.08    # ctrl 누른 뒤 클릭까지(초)
STEPS        = (70, 95, 120)  # 원 3단계 스텝(=반지름). 한 단계 높을수록 25씩 커짐

#innerauto 튜닝값
RETURN_WAIT  = 10      # f12 귀환 후 마을 로딩 대기(초)
INNER_IMG1   = 'inner1.PNG'   # f10 누른 뒤 찾을 이미지 (실제 파일명으로 교체)
INNER_IMG2   = 'inner2.PNG'   # f1 누른 뒤 찾을 이미지 (실제 파일명으로 교체)
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

#정사각 둘레 좌표를 중심에서 가까운 순으로 미리 계산
#steps 를 여러개 주면 반지름이 다른 원을 겹쳐서 다단계로 훑는다 (안쪽 원부터 스캔)
def _scanpoints(p, ln, steps=STEPS):
    half = (ln - 1) // 2
    seen = set()
    pts  = []
    for step in steps:
        for dx in range(-half, half + 1):
            for dy in range(-half, half + 1):
                if dx == 0 and dy == 0:
                    continue
                q = (p[0] + dx * step, p[1] + dy * step)
                if q in seen:      #안쪽 원과 겹치는 좌표는 버림
                    continue
                seen.add(q)
                pts.append(q)
    pts.sort(key=lambda q: (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2)
    return pts

#용던
def attack1(p,len,atkvalue):
    global isture
    global ishunting
    if(len%2 == 0):
        print('len 홀수로 지정')
        return

    points  = _scanpoints(p, len)
    parkpos = (p[0], p[1] + 350)
    dirty   = False   #직전 프로브 히트 -> 커서가 공격모양으로 남아있음
    cnt     = 0       #클릭 없이 헛돈 횟수

    while isture:
        if ishunting != 0:
            time.sleep(0.2)   #풀스핀 방지
            continue

        sc.run_pending()

        cnt += 1
        if cnt >= 15:         #10바퀴 동안 못 잡으면 f5
            gu.press('f5', presses=1)
            cnt = 0

        for (x, y) in points:
            if (not isture) or ishunting != 0:
                break
            if 19:                    #히트 직후에만 커서 초기화
                _movefast(parkpos[0], parkpos[1])
                time.sleep(PROBE_SETTLE)
                dirty = False
            if _probe(x, y, atkvalue):
                gu.keyDown('ctrl')
                time.sleep(CTRL_DELAY)
                gu.click()
                gu.keyUp('ctrl')
                dirty = True
                cnt = 0
                break                       #가까운 좌표부터 다시 스캔
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
VK_HANGUL       = 0x15
KEYEVENTF_KEYUP = 0x0002

def _togglehangul():
    win32api.keybd_event(VK_HANGUL, 0, 0, 0)
    time.sleep(0.05)
    win32api.keybd_event(VK_HANGUL, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.2)

#채팅창에 ".버프" 입력 (매크로 명령어)
def sendbuffchat():
    print('.버프 입력')
    gu.press('enter', presses=1)        #채팅창 열기
    time.sleep(0.3)
    k.write('.버프', delay=0.05)        #유니코드로 직접 주입 (IME 안 거침)
    time.sleep(0.3)
    #한/영 토글이 게임 창에 안 먹혀서 .qjvm 이 그대로 찍힘. 아래 IME 방식은 보류
    # _togglehangul()                        #한글 입력 모드로 전환
    # gu.typewrite('.qjvm', interval=0.05)   # . + 버(qj) + 프(vm)
    # time.sleep(0.3)
    # _togglehangul()                        #영문 모드로 복구 (F키 단축키 보호)
    gu.press('enter', presses=1)        #전송

def setbuff30():
    time.sleep(1)
    gu.press('f6', presses=1)
    time.sleep(1)
    gu.press('f7', presses=1)
    time.sleep(1)
    gu.press('f9', presses=1)
    time.sleep(1)
    sendbuffchat()

    threading.Timer(1800, setbuff30).start()

def setbuff10():
    gu.press('f10', presses=1)
    time.sleep(1)
    sendbuffchat()

    threading.Timer(300, setbuff10).start()

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

#귀환 후 마무리 : f10 -> 이미지클릭 -> f1 -> 이미지클릭 -> 스크립트 종료
def innerauto():
    print('innerauto 시작')

    #1. f10
    gu.press('f10', presses=1)
    time.sleep(1)
    #2~3. 이미지 찾고 클릭
    if not _findandclick(INNER_IMG1):
        print('innerauto 중단 - 스크립트 종료')
        os._exit(1)
    time.sleep(1)

    #4. f1
    gu.press('f1', presses=1)
    time.sleep(1)
    #5~6. 이미지 찾고 클릭
    if not _findandclick(INNER_IMG2):
        print('innerauto 중단 - 스크립트 종료')
        os._exit(1)
    time.sleep(1)

    #7. 시스템 종료 (매크로 프로세스만 즉시 종료)
    print('innerauto 완료 - 스크립트 종료')
    os._exit(0)

#피 확인
def checkrHp():
    global isture
    file_path = IMAGE_DIR
    checkrmp = gu.locateCenterOnScreen(file_path + 'checkhp.PNG', confidence=0.8)
    if checkrmp != None:
        print('피 소모 완료 귀한!')
        gu.press('f12', presses=1)
        isture=False
        time.sleep(RETURN_WAIT)   #귀환 완료 대기
        innerauto()               #여기서 프로세스가 끝나므로 타이머 재등록 안함
        return
    threading.Timer(1, checkrHp).start()
#변신
def transform():
    gu.press('f11', presses=1)
    file_path = IMAGE_DIR
    lv80 = gu.locateCenterOnScreen(file_path + 'lv80.PNG', confidence=0.8)
    if lv80 != None:
        gu.moveTo(lv80)
        gu.click()
        knight = gu.locateCenterOnScreen(file_path + 'night.PNG', confidence=0.8)
        if knight != None:
            gu.moveTo(knight)
            gu.click()

    threading.Timer(1200, transform).start()

if __name__ == '__main__':

    count = 1
    attackinfo=[]
    centerpoint = [625, 480]
    #FAILSAFE 대체 : tab 으로 즉시 종료
    k.add_hotkey('tab', lambda: os._exit(0))
    attackinfo = setattckinfo(centerpoint)
    transform()
    print(attackinfo)

    checkrHp()
    setbuff10()
    setbuff30()

    print(attackinfo)
    while isture:
        if ishunting == 0:
            sc.run_pending()
            #기존 스캔박스 위치 유지 (원본 시작점이 y로 40px 위에 잡혔음)
            attack1([centerpoint[0], centerpoint[1] - 40], 3, attackinfo)

            count += 1
            if count % 10 == 0:
                print('10회마다 새로고침')
                gu.press('f5', presses=1)
                count=0












