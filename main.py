import time
import win32gui
import win32api
import pyautogui as gu
import schedule as sc
import keyboard as k
import time
import threading
import os.path

ishunting =0
isture=True

#탐색 튜닝값 (실기에서 조정)
PROBE_SETTLE = 0.025   # 커서 모양 갱신 대기 최대치(초)
PROBE_STEP   = 0.003   # 폴링 간격(초)
CTRL_DELAY   = 0.08    # ctrl 누른 뒤 클릭까지(초)
def getcursorinfo():
    #기본커서 65539
    #칼커서 3017359
    #11865074
    return win32gui.GetCursorInfo()[1]
def pushkeyboard():
    print('프로그램종료')
    gu.press('f10', presses=1)
    exit()
def windshotandiofstom():
    print('windshotandiofstom')
    time.sleep(2)
    gu.press('f10', presses=1)
    time.sleep(2)
    gu.press('f11', presses=1)
    time.sleep(1)
    gu.press('f12', presses=1)
def windshotandiofstom1():
    print('windshotandiofstom1')
    gu.press('f7', presses=1)
    time.sleep(2)
    gu.press('f8', presses=1)

def delmagic():
    print('delmagic')
    time.sleep(0.5)
    gu.press('f9', presses=1)
    time.sleep(0.5)
    gu.press('f9', presses=1)
    time.sleep(0.5)
    gu.press('f9', presses=1)
    time.sleep(0.5)
    gu.press('f9', presses=1)
    time.sleep(0.5)
    gu.press('f9', presses=1)
    time.sleep(0.5)
    gu.press('f10', presses=1)
    time.sleep(0.5)
    gu.press('f10', presses=1)
    time.sleep(0.5)
    gu.press('f10', presses=1)
    time.sleep(0.5)
    gu.press('f10', presses=1)
    time.sleep(0.5)
    gu.press('f10', presses=1)
    time.sleep(0.5)
    gu.press('f11', presses=1)
    time.sleep(0.5)
    gu.press('f11', presses=1)
    time.sleep(0.5)
    gu.press('f11', presses=1)
    time.sleep(0.5)
    gu.press('f11', presses=1)
    time.sleep(0.5)
    gu.press('f11', presses=1)
    time.sleep(0.5)
    gu.press('f12', presses=1)
    time.sleep(0.5)
    gu.press('f12', presses=1)
    time.sleep(0.5)
    gu.press('f12', presses=1)
    time.sleep(0.5)
    gu.press('f12', presses=1)
    time.sleep(0.5)
    gu.press('f12', presses=1)
    threading.Timer(600, delmagic).start()
def morefast():
    print('morefast')
    gu.press('f7', presses=1)
    time.sleep(3)
    gu.press('f8', presses=1)
    threading.Timer(600, morefast).start()


#
def fool(p,atkvalue):
    gu.moveTo(p[0] + 20, p[1] + 400)
    time.sleep(0.5)
    # gu.moveTo(p[0]+30, p[1]-30)
    while True:
        gu.moveTo(p[0]-20, p[1])
        if (win32gui.GetCursorInfo()[1] == atkvalue):
            gu.keyDown('ctrl')
            time.sleep(0.5)
            gu.doubleClick()
            gu.keyUp('ctrl')
            gu.moveTo(p[0] + 20, p[1] + 400)
        gu.moveTo(p[0], p[1]+20)
        if (win32gui.GetCursorInfo()[1] == atkvalue):
            gu.keyDown('ctrl')
            time.sleep(0.5)
            gu.doubleClick()
            gu.keyUp('ctrl')
            gu.moveTo(p[0] + 20, p[1] + 400)
        gu.moveTo(p[0]+20, p[1] + 20)
        if (win32gui.GetCursorInfo()[1] == atkvalue):
            gu.keyDown('ctrl')
            time.sleep(0.5)
            gu.doubleClick()
            gu.keyUp('ctrl')
            gu.moveTo(p[0] + 20, p[1] + 400)


#용던
def attack(p,len,atkvalue):
    isattack = True
    cnt =0
    if(len%2 == 0):
        print('len 홀수로 지정')
    else:

        #시작지점
        startPoint=[p[0]-(((len-1)/2)*50),p[1]-(((len-1)/2)*90)]

        #->
        for i in range(0,len-1):
            startPoint[0]=startPoint[0]+50
            gu.moveTo(startPoint[0], startPoint[1])
            gu.keyDown('ctrl')
            time.sleep(1)
            gu.doubleClick()

            cnt = 0
        #아래로
        for j in range(0,len-1):
            startPoint[1] = startPoint[1] + 50
            gu.moveTo(startPoint[0], startPoint[1])
            gu.keyDown('ctrl')
            time.sleep(1)
            gu.doubleClick()

            cnt = 0
        # <-
        for i in range(0, len - 1):
            startPoint[0] = startPoint[0] - 50
            gu.moveTo(startPoint[0], startPoint[1])
            gu.keyDown('ctrl')
            gu.doubleClick()
            time.sleep(1)
            cnt = 0
        #위로
        for j in range(0,len-1):
            startPoint[1] = startPoint[1] - 50
            gu.moveTo(startPoint[0], startPoint[1])
            gu.keyDown('ctrl')
            time.sleep(1)
            gu.doubleClick()
            cnt = 0


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
def _scanpoints(p, ln, step=50):
    half = (ln - 1) // 2
    pts = [(p[0] + dx * step, p[1] + dy * step)
           for dx in range(-half, half + 1)
           for dy in range(-half, half + 1)
           if not (dx == 0 and dy == 0)]
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
    parkpos = (p[0], p[1] + 400)
    dirty   = False   #직전 프로브 히트 -> 커서가 공격모양으로 남아있음

    while isture:
        if ishunting != 0:
            time.sleep(0.2)   #풀스핀 방지
            continue

        sc.run_pending()

        for (x, y) in points:
            if (not isture) or ishunting != 0:
                break
            if dirty:                    #히트 직후에만 커서 초기화
                _movefast(parkpos[0], parkpos[1])
                time.sleep(PROBE_SETTLE)
                dirty = False
            if _probe(x, y, atkvalue):
                gu.keyDown('ctrl')
                time.sleep(CTRL_DELAY)
                gu.click()
                gu.keyUp('ctrl')
                dirty = True
                break                    #가까운 좌표부터 다시 스캔
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


#보상확인하기
def checkrMp():
    file_path = os.path.dirname(os.path.realpath(__file__)) + '\\' + 'image' + '\\'
    checkrmp = gu.locateCenterOnScreen(file_path + 'checkmp1.PNG', confidence=0.8)
    if checkrmp == None:
        print('파톰 완료')
        gu.press('f6', presses=1)
        ishunting=1

    threading.Timer(1, checkrMp).start()
#마크 확인
def checkrMark():
    global ishunting
    global isture
    if ishunting == 0:
        file_path = os.path.dirname(os.path.realpath(__file__)) + '\\' + 'image' + '\\'
        mark1 = gu.locateCenterOnScreen(file_path + 'mark1.PNG', confidence=0.8)
        mark2 = gu.locateCenterOnScreen(file_path + 'mark2.PNG', confidence=0.8)
        if mark1 != None:
            print('혈마크 감지')
            gu.press('f8', presses=1)
            ishunting=2
            isture =False
            exit()
        if mark2 != None:
            print('혈마크 감지')
            gu.press('f8', presses=1)
            ishunting=2
            isture = False
            exit()

    threading.Timer(1, checkrMark).start()

def setbuff10():
    time.sleep(1)
    gu.press('f9', presses=1)

    threading.Timer(1800, setbuff10).start()
#피 확인
def checkrHp():
    global isture
    file_path = os.path.dirname(os.path.realpath(__file__)) + '\\' + 'image' + '\\'
    checkrmp = gu.locateCenterOnScreen(file_path + 'checkhp.PNG', confidence=0.8)
    if checkrmp != None:
        print('피 소모 완료 귀한!')
        gu.press('f8', presses=1)
        isture=False
    threading.Timer(1, checkrHp).start()
#변신
def transform():
    gu.press('f11', presses=1)
    file_path = os.path.dirname(os.path.realpath(__file__)) + '\\' + 'image' + '\\'
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
    #False d오른쪽이동 True 왼쪽이동
    direction=False
    centerpoint = [625, 480]
    #FAILSAFE 대체 : tab 으로 즉시 종료
    k.add_hotkey('tab', lambda: os._exit(0))
    attackinfo = setattckinfo(centerpoint)
    # transform()
    print(attackinfo)
    # morefast()
    # checkrMp()
    # delmagic()


    checkrHp()
    # checkrMark()
    setbuff10()

    # attackinfo=1018953961
    print(attackinfo)
    while isture:
        if ishunting == 0:
            sc.run_pending()
            # fool(centerpoint,attackinfo)
            #기존 스캔박스 위치 유지 (원본 시작점이 y로 40px 위에 잡혔음)
            attack1([centerpoint[0], centerpoint[1] - 40], 3, attackinfo)
            # atta  ck(centerpoint, 3, attackinfo)

            # fool(centerpoint,attackinfo)
            # time.sleep(1)
            # result = attack_one(centerpoint,3,attackinfo)
            # if(result):
            #     attack_one(centerpoint, 13, attackinfo)

            count += 1
            # gu.press('f5', presses=1)












