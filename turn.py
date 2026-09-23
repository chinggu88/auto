import time
import win32gui
import pyautogui as gu
import schedule as sc
import keyboard as k
import time
import threading
import os.path

gu.FAILSAFE = False
#최신 pyautogui 는 이미지 못 찾으면 None 대신 ImageNotFoundException 을 던짐
#아래 코드 전체가 None 비교를 전제로 하므로 예전 동작(None 반환)으로 되돌림
gu.useImageNotFoundException(False)
isattack = True
#원 3단계 스텝(=반지름). 한 단계 높을수록 20씩 커짐
STEPS = (56, 79, 101)
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

#용던
def attack1(p,len,atkvalue):
    print('isattack')
    global isattack
    print(isattack)
    cnt =0
    if(len%2 == 0):
        print('len 홀수로 지정')
    else:
        while True:
            if(isattack==True):
                #원 3단계 - 안쪽부터 바깥쪽으로 반지름 20씩 키워가며 훑는다
                for step in STEPS:
                    #시작지점 (step+40 이면 세 원의 중심이 같은 지점에 유지됨)
                    startPoint=[p[0]-(((len-1)/2)*step),p[1]-(((len-1)/2)*(step+45))]

                    #->
                    for i in range(0,len-1):
                        gu.moveTo(startPoint[0], startPoint[1] + 450)
                        startPoint[0]=startPoint[0]+step
                        gu.moveTo(startPoint[0], startPoint[1])
                        if (win32gui.GetCursorInfo()[1] == atkvalue):
                            # gu.keyDown('ctrl')
                            time.sleep(0.5)
                            gu.doubleClick()
                            # gu.keyUp('ctrl')
                            cnt = 0
                    #아래로
                    for j in range(0,len-1):
                        gu.moveTo(startPoint[0], startPoint[1] + 450)
                        startPoint[1] = startPoint[1] + step
                        gu.moveTo(startPoint[0], startPoint[1])
                        if (win32gui.GetCursorInfo()[1] == atkvalue):
                            # gu.keyDown('ctrl')
                            time.sleep(0.5)
                            gu.doubleClick()
                            # gu.keyUp('ctrl')
                            cnt = 0
                    # <-
                    for i in range(0, len - 1):
                        gu.moveTo(startPoint[0], startPoint[1] + 450)
                        startPoint[0] = startPoint[0] - step
                        gu.moveTo(startPoint[0], startPoint[1])
                        if (win32gui.GetCursorInfo()[1] == atkvalue):
                            # print('공격')
                            # gu.keyDown('ctrl')
                            time.sleep(0.5)
                            gu.doubleClick()
                            # gu.keyUp('ctrl')
                            cnt = 0
                    #위로
                    for j in range(0,len-1):
                        gu.moveTo(startPoint[0], startPoint[1] + 450)
                        startPoint[1] = startPoint[1] - step
                        gu.moveTo(startPoint[0], startPoint[1])
                        if (win32gui.GetCursorInfo()[1] == atkvalue):
                            # gu.keyDown('ctrl')
                            time.sleep(0.5)
                            gu.doubleClick()
                            # gu.keyUp('ctrl')
                            cnt = 0

                    cnt +=1
                    if (cnt == 3):
                        gu.press('f5', presses=1)
                        cnt = 0

#피 확인
def checkrHp():
    global isattack
    file_path = os.path.dirname(os.path.realpath(__file__)) + '\\' + 'image' + '\\'
    checkrmp = gu.locateCenterOnScreen(file_path + 'checkhp.PNG', confidence=0.8)
    if checkrmp != None:
        print('피 소모 완료 귀한!')
        gu.press('f5', presses=1)
        #gu.press('f8', presses=1)
        #isattack=False
    threading.Timer(1, checkrHp).start()

#변신
def transform():
    global isattack
    gu.press('f12', presses=1)
    file_path = os.path.dirname(os.path.realpath(__file__)) + '\\' + 'image' + '\\'
    lv80 = gu.locateCenterOnScreen(file_path + 'lv80.PNG', confidence=0.8)
    if lv80 != None:
        isattack = False
        time.sleep(2)
        gu.moveTo(lv80)
        gu.click()
        isattack = True
    threading.Timer(600, transform).start()

#버프
def checkrbuff20():
    gu.press('f6', presses=1)
    time.sleep(1)
    gu.press('f7', presses=1)
    time.sleep(1)
    threading.Timer(1200, checkrbuff20).start()

# 버프
def checkrbuff10():
    gu.press('f10', presses=1)
    time.sleep(1)
    gu.press('f11', presses=1)
    time.sleep(1)
    gu.press('f9', presses=1)
    threading.Timer(600, checkrbuff10).start()
#마크 확인
def checkrMark():
    global isattack
    file_path = os.path.dirname(os.path.realpath(__file__)) + '\\' + 'image' + '\\'
    # mark1 = gu.locateCenterOnScreen(file_path + 'mark1.PNG', confidence=0.5)
    # mark2 = gu.locateCenterOnScreen(file_path + 'mark2.PNG', confidence=0.5)
    # mark3 = gu.locateCenterOnScreen(file_path + 'mark3.PNG', confidence=0.1)
    mark4 = gu.locateCenterOnScreen(file_path + 'mark4.PNG', confidence=0.2)
    if isattack == True:
        if mark4 != None:
            # if mark2[0] <= 633:
            if mark4[0] <= 675 & mark4[0] >= 731:
                if mark4[1] != 389:
                    gu.press('f8', presses=1)
                    isattack = False
                    print('혈마크 감지4')
                    print(isattack)
        # if mark2 != None:
        #     gu.press('f8', presses=1)
        #     isattack = False
        #     print('혈마크 감지2')
        #     print(isattack)
        # if mark3 != None:
        #     gu.press('f8', presses=1)
        #     isattack = False
        #     print('혈마크 감지3')
        #     print(isattack)


    threading.Timer(3, checkrMark).start()
if __name__ == '__main__':
    # file_path = os.path.dirname(os.path.realpath(__file__)) + '\\' + 'image' + '\\'
    centerpoint = [720, 540]
    attackinfo = setattckinfo(centerpoint)
    checkrMark()
    transform()
    # checkrbuff20()
    # checkrbuff10()
    # checkrHp()
    # attack1(centerpoint, 3, attackinfo)

    #오만

    #힐사용하기
    # checkrMp()

