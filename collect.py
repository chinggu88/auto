# -*- coding: utf-8 -*-
#=====================================================================
# YOLO 학습 데이터 수집기 (Windows 전용)
#
# 원리 : 커서 모양이 공격 커서로 바뀌는 지점 = 공격 가능한 대상이 있는 자리
#        main.py 가 이미 하고 있는 판별을 그대로 써서 라벨을 자동으로 만든다
#        -> 수작업 라벨링도, 클라이언트 리버싱도 필요 없다
#
# 한 샘플을 만드는 순서 (순서가 중요하다) :
#   1. 스캔점을 훑다가 공격 커서가 뜨면 그 좌표를 중심으로 잡는다
#   2. 상하좌우로 프로브를 넓혀 공격 커서가 끊기는 지점을 찾는다 -> 바운딩 박스
#   3. 커서를 파크로 치운 뒤 잠깐 기다린다
#      (커서를 올려야만 뜨는 이름표/체력바가 사라져야 한다. 안 그러면 모델이
#       '이름표가 보이면 몬스터' 를 배워버려서 실전에서 전혀 안 맞는다)
#   4. 화면을 찍는다
#   5. 중심을 다시 프로브해서 아직 대상이 그 자리에 있는지 확인한다
#      (2~4 사이에 몹이 걸어가 버렸으면 라벨이 어긋나므로 버린다)
#
# main.py 를 import 해서 쓴다. 판별 함수와 상수를 복사하지 않아야
# 수집한 라벨과 실제 매크로가 보는 것이 어긋나지 않는다
#=====================================================================
import os
import sys
import time
import random

import win32gui
import keyboard as k
import pyautogui as gu

import main as M      #main.py 는 __main__ 가드가 있어서 import 해도 GUI 가 안 뜬다

#--- 수집 설정 -------------------------------------------------------
BOX_STEP    = 10     #박스 경계를 찾을 때 한 번에 넓히는 픽셀
BOX_LIMIT   = 70     #중심에서 이 이상은 안 찾는다(px). 옆 몹까지 삼키지 않게
BOX_MIN     = 12     #이보다 작은 박스는 버린다. 커서가 튄 것일 가능성이 높다
HOVER_CLEAR = 0.18   #파크로 치운 뒤 이름표가 사라지기를 기다리는 시간(초)
NEG_EVERY   = 3      #스윕을 이 횟수만큼 헛돌 때마다 음성 샘플(몹 없는 화면)을 1장 찍는다
JPEG_Q      = 90     #PNG 로 두면 장당 1~2MB 라 2천 장에 4GB 다. 학습에는 JPEG 로 충분하다

STOPKEY     = 'tab'  #main.py 와 같은 키로 멈춘다
RUN         = True


def _stop():
    global RUN
    RUN = False


#(cx,cy) 에서 (dx,dy) 방향으로 공격 커서가 끊기는 직전까지의 거리를 돌려준다
def _edge(cx, cy, dx, dy, atk):
    last = 0
    d    = BOX_STEP
    while d <= BOX_LIMIT:
        if not M._probe(cx + dx * d, cy + dy * d, atk):
            break
        last = d
        d   += BOX_STEP
    return last


#화면 좌표 박스를 캡처 영역 기준 YOLO 라벨(정규화 cx cy w h)로 바꾼다
def _tolabel(box, region):
    l, t, w, h = region
    x1, y1, x2, y2 = box
    cx = ((x1 + x2) * 0.5 - l) / float(w)
    cy = ((y1 + y2) * 0.5 - t) / float(h)
    bw = (x2 - x1) / float(w)
    bh = (y2 - y1) / float(h)
    if cx < 0 or cy < 0 or cx > 1 or cy > 1:
        return None                     #캡처 영역 밖이면 버린다
    return '0 %.6f %.6f %.6f %.6f' % (cx, cy, bw, bh)


def _save(img, lines, outdir, tag, n):
    name = '%s_%05d' % (tag, n)
    img.save(os.path.join(outdir, 'images', name + '.jpg'), quality=JPEG_Q)
    f = open(os.path.join(outdir, 'labels', name + '.txt'), 'w')
    f.write('\n'.join(lines) + ('\n' if lines else ''))
    f.close()


def collect(tag, target):
    global RUN
    outdir = os.path.join(M.APP_DIR, 'dataset')
    for sub in ('images', 'labels'):
        d = os.path.join(outdir, sub)
        if not os.path.isdir(d):
            os.makedirs(d)

    print('게임 창을 활성화하세요...')
    for i in range(M.START_DELAY, 0, -1):
        print('  ' + str(i))
        time.sleep(1)

    #활성 창을 캡처 영역으로 쓴다. 카운트다운 뒤라 게임 창이 앞에 있다
    hwnd = win32gui.GetForegroundWindow()
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    region = (l, t, r - l, b - t)
    print('캡처 영역 : %d,%d  %dx%d   (%s)'
          % (region[0], region[1], region[2], region[3], win32gui.GetWindowText(hwnd)))

    atk = M.setattckinfo(M.CENTERPOINT)
    print('공격 커서 : ' + str(atk))

    p       = [M.CENTERPOINT[0], M.CENTERPOINT[1] + M.SCAN_OFFSET_Y]
    M.SCAN_ROUND = M.SCAN_FAR          #수집은 넓게 훑는다
    points  = M._scanpoints(p)
    parkpos = (p[0], p[1] + M.SCAN_START * M.SCAN_FAR + M.PARK_GAP)

    k.add_hotkey(STOPKEY, _stop)
    print(STOPKEY + ' 키를 누르면 정지.  목표 ' + str(target) + '장')

    n = miss = idx = 0
    kept = dropped = neg = 0
    while RUN and n < target:
        x, y = points[idx]
        idx  = (idx + 1) % len(points)
        if idx == 0:
            miss += 1
            #몹을 하나도 못 찾은 바퀴 -> 음성 샘플(배경만 있는 화면)
            if miss % NEG_EVERY == 0:
                M._movefast(parkpos[0], parkpos[1])
                time.sleep(HOVER_CLEAR)
                _save(gu.screenshot(region=region), [], outdir, tag, n)
                n += 1; neg += 1
                print('  [%4d] 음성' % n)

        M._movefast(parkpos[0], parkpos[1])
        time.sleep(M.PROBE_SETTLE)
        if not M._probe(x, y, atk):
            continue

        miss = 0
        #--- 2. 박스 재기 ---
        lft = _edge(x, y, -1,  0, atk)
        rgt = _edge(x, y,  1,  0, atk)
        up  = _edge(x, y,  0, -1, atk)
        dn  = _edge(x, y,  0,  1, atk)
        box = (x - lft, y - up, x + rgt, y + dn)
        if (box[2] - box[0]) < BOX_MIN or (box[3] - box[1]) < BOX_MIN:
            dropped += 1
            continue

        #--- 3~4. 커서를 치우고 이름표가 사라진 뒤 촬영 ---
        M._movefast(parkpos[0], parkpos[1])
        time.sleep(HOVER_CLEAR)
        img = gu.screenshot(region=region)

        #--- 5. 아직 그 자리에 있나 확인. 없으면 라벨이 어긋난 것이라 버린다 ---
        if not M._probe(x, y, atk):
            dropped += 1
            continue

        line = _tolabel(box, region)
        if line == None:
            dropped += 1
            continue

        _save(img, [line], outdir, tag, n)
        n += 1; kept += 1
        print('  [%4d] 박스 %dx%d  @%d,%d' % (n, box[2] - box[0], box[3] - box[1], x, y))

    try:
        k.remove_hotkey(STOPKEY)
    except Exception:
        pass

    #ultralytics 가 바로 읽는 data.yaml 을 같이 써 둔다
    f = open(os.path.join(outdir, 'data.yaml'), 'w', encoding='utf-8')
    f.write('path: %s\ntrain: images\nval: images\nnc: 1\nnames: [target]\n'
            % outdir.replace('\\', '/'))
    f.close()

    print('')
    print('저장 : ' + outdir)
    print('양성 %d장 / 음성 %d장 / 버림 %d개' % (kept, neg, dropped))
    print('버림이 양성보다 많으면 몹이 너무 빨리 움직이는 것입니다. HOVER_CLEAR 를 줄여보세요')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('사용법 : python collect.py <사냥터이름> [장수]')
        print('  예   : python collect.py 용던 800')
        sys.exit(1)
    collect(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 500)
