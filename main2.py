import pyautogui as m
import keyboard
import os.path
import time
import threading
import win32gui
from datetime import datetime

#최신 pyautogui 는 이미지 못 찾으면 None 대신 ImageNotFoundException 을 던짐
#아래 코드 전체가 None 비교를 전제로 하므로 예전 동작(None 반환)으로 되돌림
m.useImageNotFoundException(False)

#0 사냥중 1 휴식중
ishunting =1
#사냥 시작시간
starttime =datetime.now()
#어택 마우스 셋팅
def setattckinfo(centerpoint):
    m.moveTo(centerpoint)
    time.sleep(0.1)
    m.click()
    time.sleep(0.1)
    m.keyDown('ctrl')
    time.sleep(0.1)
    info = win32gui.GetCursorInfo()[1]
    time.sleep(0.1)
    m.keyUp('ctrl')
    return info

#마나확인
def checkrMp():
    global ishunting
    checkrmp = m.locateCenterOnScreen(file_path + 'checkmp.PNG', confidence=0.8)
    if checkrmp != None:
        print('엠피소모 완료 귀한!')
        m.press('f8', presses=1)
        time.sleep(1)
        m.press('f12', presses=1)
        ishunting = 2
    threading.Timer(1, checkrMp).start()

#피 확인
def checkrHp():
    global ishunting
    checkrmp = m.locateCenterOnScreen(file_path + 'checkhp.PNG', confidence=0.8)
    if checkrmp != None:
        print('피 소모 완료 귀한!')
        m.press('f8', presses=1)
        time.sleep(1)
        m.press('f12', presses=1)
        ishunting=2
        exit()
    threading.Timer(1, checkrHp).start()

#버프쓰게
def checkrbuff():
    m.press('f9', presses=1)
    time.sleep(2)
    m.press('f10', presses=1)
    time.sleep(2)
    m.press('f11', presses=1)
    threading.Timer(1500, checkrbuff).start()

#마크 확인
def checkrMark():
    print('마크체크')
    global ishunting
    mark1 = m.locateCenterOnScreen(file_path + 'mark1.PNG', confidence=0.8)
    mark2 = m.locateCenterOnScreen(file_path + 'mark2.PNG', confidence=0.8)
    if ishunting == 0:
        if mark1 != None:
            print('혈마크 감지')
            m.press('f8', presses=1)
            ishunting=2
        if mark2 != None:
            print('혈마크 감지')
            m.press('f8', presses=1)
            ishunting=2

    threading.Timer(1, checkrMark).start()

if __name__ == '__main__':
    file_path = os.path.dirname(os.path.realpath(__file__)) + '\\' + 'image' + '\\'
    # checkrMp(file_path)
    #칼모양셋팅
    centerpoint = [720, 540]
    attackinfo = setattckinfo(centerpoint)

    # checkrMp()
    checkrHp()
    # checkrbuff()
    # checkrMark()
    while True:
        # 수동사냥
        if (win32gui.GetCursorInfo()[1] == attackinfo):
            m.middleClick()
        # if ishunting == 0:
        #     #특정시간후 귀한
        #     diff = time.time()-starttime
        #     if diff > 50:
        #         m.press('f8', presses=1)
        #         time.sleep(1)
        #         m.press('f12', presses=1)
        #         ishunting = 2
        #     type1 = m.locateCenterOnScreen(file_path + 'type5.PNG', confidence=0.8)
        #     if(type1 != None):
        #         m.moveTo(type1[0],type1[1]+150)
        #         m.click(button='middle')
        #     elif(type1 == None):
        #         type2 = m.locateCenterOnScreen(file_path + 'type2.PNG', confidence=0.8)
        #         if (type2 != None):
        #             m.moveTo(type2[0], type2[1] + 150)
        #             m.click(button='middle')
        #         elif (type2 == None):
        #             type3 = m.locateCenterOnScreen(file_path + 'type3.PNG', confidence=0.8)
        #             if (type3 != None):
        #                 m.moveTo(type3[0], type3[1] + 150)
        #                 m.click(button='middle')
        #             elif (type3 == None):
        #                 type4 = m.locateCenterOnScreen(file_path + 'type4.PNG', confidence=0.8)
        #                 if (type4 != None):
        #                     m.moveTo(type4[0], type4[1] + 150)
        #                     m.click(button='middle')
        #                 elif (type4 == None):
        #                     type5 = m.locateCenterOnScreen(file_path + 'type1.PNG', confidence=0.8)
        #                     if (type5 != None):
        #                         m.moveTo(type5[0], type5[1] + 150)
        #                         m.click(button='middle')
        # elif ishunting == 1:
        #     checkmp3 = m.locateCenterOnScreen(file_path + 'checkmp3.PNG', confidence=0.9)
        #     if(checkmp3 != None):
        #         starttime = time.time()
        #         m.moveTo(centerpoint)
        #         m.press('f6', presses=1)
        #         m.click()
        #         print('사냥시작 시간',starttime)
        #         m.press('f7', presses=1)
        #         ishunting = 0
        #
        # elif ishunting == 2:
        #     time.sleep(10)
        #     ishunting=1