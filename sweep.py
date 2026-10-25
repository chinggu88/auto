# sweep.py
#
# main.py 변형 버전. 이것만 한다:
#   1. 화면 전체에서 이미지 1개를 전수 스캔해서 매칭된 위치를 전부 찾는다
#   2. 각 위치에서 50px 아래로 이동한 뒤 휠(중간) 클릭 -> 0.5초 -> 휠 위 1회 + 클릭 -> 0.5초 -> 휠 아래 1회 (순차 반복)
#   3. 0.5초 쉬고 다시 돈다 (매칭이 있을 때만 로그)
#
# main.py 와 같은 폴더에 넣고 실행 :  python sweep.py
# (pit.py 처럼 `import main` 으로 공용 헬퍼를 재사용한다. main.py 는 수정하지 않는다)

import time
import os.path

import keyboard as k

import main
from main import gu

#=====================================================================
# 설정 : 여기만 고치면 된다
#=====================================================================
TARGET_IMG = 'target.png'   # image\ 폴더에 넣어둔 찾을 이미지 1장
CONF       = 0.8            # 매칭 신뢰도(0~1). 너무 많이 잡히면 올리고, 못 찾으면 내린다
REPEAT_SEC = 0.5            # 한 바퀴 돌고 쉬는 시간(초)
CLICK_DY   = 50             # 매칭 위치에서 아래로 내린 지점을 클릭(px)
SETTLE_SEC = 0.1            # 이동 후 클릭까지 대기(초)
WHEEL_GAP  = 0.5            # 클릭 후 휠 이동까지 대기(초)
STOP_KEY   = 'esc'          # 이 키를 누르면 종료
#=====================================================================

gu.FAILSAFE = True          # 마우스 모서리 탈출 켜둠 (oman/tell/turn 과 다르게)


def scan_all():
    """화면 전체에서 TARGET_IMG 와 매칭되는 위치를 전부 찾아 중심 좌표 리스트로 돌려준다."""
    path = os.path.join(main.IMAGE_DIR, TARGET_IMG)

    #cv2/numpy 가 있으면 main.py 의 마스크 매칭 + 직접 NMS 로 전수 탐색
    if main.MASK_OK:
        hay = main.screengrab()
        needle, mask, cnt = main._marktpl(path)
        if needle is None:
            return []
        res = main.cv2.matchTemplate(hay, needle, main.cv2.TM_SQDIFF, mask=mask)
        res = main.numpy.where(main.numpy.isfinite(res), res, main.numpy.inf)
        #픽셀당 평균 오차 -> 0~1 점수. 1.0 이면 완전히 같다 (findmark 와 같은 식)
        score = 1.0 - main.numpy.sqrt(main.numpy.clip(res, 0, None) / (cnt * 3.0)) / 255.0

        ys, xs = main.numpy.where(score >= CONF)
        if len(xs) == 0:
            return []
        h, w = needle.shape[0], needle.shape[1]
        pts = []
        #점수 높은 순으로 보면서, 이미 뽑은 자리와 겹치면 버린다 (같은 물체의 중복 제거)
        for i in main.numpy.argsort(-score[ys, xs]):
            x = int(xs[i]) + w // 2
            y = int(ys[i]) + h // 2
            if all(abs(x - px) >= w or abs(y - py) >= h for px, py in pts):
                pts.append((x, y))
        return pts

    #cv2 가 없으면 pyautogui 전수 탐색으로 폴백
    pts = []
    for box in gu.locateAllOnScreen(path, confidence=CONF):
        pts.append((box.left + box.width // 2, box.top + box.height // 2))
    return pts


def _safemove(x, y):
    """마우스 이동. SetCursorPos 가 실패하면(화면 밖 좌표, 입력 차단 등)
    pyautogui 방식(mouse_event)으로 폴백한다."""
    sw, sh = gu.size()
    x = max(0, min(sw - 1, int(x)))
    y = max(0, min(sh - 1, int(y)))
    try:
        main._movefast(x, y)
    except Exception as e:
        main.log('SetCursorPos 실패(%d,%d) : %s -> pyautogui 로 폴백' % (x, y, e))
        gu.moveTo(x, y)


def hit(x, y):
    """한 위치 공격 : 매칭 위치에서 CLICK_DY 만큼 아래로 이동 후 휠(중간) 클릭,
    0.5초 뒤 휠 위로 1회 + 클릭, 0.5초 뒤 휠 아래로 1회."""
    tx, ty = x, y + CLICK_DY
    _safemove(tx, ty)
    time.sleep(SETTLE_SEC)
    gu.middleClick()
    main.log('타격 : %d,%d  (휠클릭)' % (tx, ty))
    time.sleep(WHEEL_GAP)
    gu.scroll(1)            # 휠 위로 1회
    gu.middleClick()
    time.sleep(WHEEL_GAP)
    gu.scroll(-1)           # 휠 아래로 1회 (원위치)


def repeat():
    """0.5초 간격 반복 : 전체 스캔 -> 각 위치마다 휠클릭 시퀀스 순차 반복."""
    imgpath = os.path.join(main.IMAGE_DIR, TARGET_IMG)
    if not os.path.isfile(imgpath):
        main.log('이미지 파일을 못 찾음 : ' + imgpath)
        main.log('image 폴더에 찾을 그림 1장을 넣고, 파일명을 TARGET_IMG 와 맞추세요 (지금 설정: ' + TARGET_IMG + ')')
        return
    main.log('sweep 시작 : %s  (신뢰도 %.2f, %s초 간격, %s=종료)'
             % (TARGET_IMG, CONF, REPEAT_SEC, STOP_KEY.upper()))
    n = 0
    while True:
        if k.is_pressed(STOP_KEY):
            break
        n += 1
        pts = scan_all()
        if pts:
            main.log('[%d] 매칭 %d개' % (n, len(pts)))
        for (x, y) in pts:
            if k.is_pressed(STOP_KEY):
                break
            hit(x, y)
        time.sleep(REPEAT_SEC)
    main.log('sweep 종료')


if __name__ == '__main__':
    try:
        repeat()
    except KeyboardInterrupt:
        main.log('sweep 종료 (Ctrl+C)')
