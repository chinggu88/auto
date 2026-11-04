# turnundead.py — 그림자신전 3층 야히의 근위병에게 턴언데드 사용 (화면 방식)
#
# main.py와 별개 파일이다. main.py를 건드리지 않고 이 파일만으로 동작한다.
# 메모리 읽지 않음. 화면에서 몹을 찾아 클릭(타게팅)하고 단축키로 턴언데드를 쓴다.
#
# 동작: 스크린샷 -> 몹 템플릿 매칭 -> 가장 중앙에 가까운 몹 클릭 -> 턴언데드 키 -> 반복
# 매칭 방식은 main.py findmark와 같은 원리 (OpenCV matchTemplate + 멀티스케일 + 신뢰도).
# 다만 main.py를 import하지 않고 이 파일 안에 독립 구현했다 (의존성 꼬임 방지).
#
# 준비물 (반드시 채울 것):
#   1. 템플릿 이미지 3개. 게임에서 몹을 캡처해 자른 PNG를 이 파일 옆 image/ 폴더에 저장:
#        yahi_demon.png     (야히의 근위병(데몬))
#        yahi_veres.png     (야히의 근위병(베레스))
#        yahi_succubus.png  (야히의 근위병(서큐버스))
#      - 몹 몸통 위주로 타이트하게 자를 것 (이름표·UI·바닥은 빼는 게 오탐이 적다).
#      - 없는 템플릿은 건너뜀 (로그에 표시). 3개 중 1개만 있어도 그 몹만 노린다.
#   2. TURNUNDEAD_KEY: 턴언데드가 박힌 단축키. 아래 설정에서 반드시 네 키로 바꿀 것.
#      (기본값 None이면 실행이 안 된다. 엉뚱한 키를 누르는 사고 방지용.)
#
# 실행 (게임 창이 포커스된 상태, 주 모니터 기준):
#   python turnundead.py --once   : 1회만 (찾기 -> 클릭 -> 스킬 1번, 테스트용)
#   python turnundead.py          : 반복 (중지: Ctrl+C 또는 마우스를 화면 왼쪽 위 모서리로)
#
# 시전 순서: 기본값은 대상 클릭 -> 단축키 (리니지 일반 스킬 방식: 타겟 지정 후 스킬 발동).
#   만약 턴언데드가 '단축키 먼저 -> 대상 클릭' 방식이면 SKILL_FIRST를 True로 바꿀 것.
#   순서가 틀리면 클릭이 일반 공격이 되니, 첫 테스트는 반드시 --once로 확인할 것.
#
# 주의: 지금은 단축키 방식이다. 길2(내부 함수 호출)로 바꾸는 건 힐 함수 사냥이
# 끝나면 그때 교체한다. 그때는 cast_turnundead() 함수만 바꾸면 된다.
#
# Windows 전용 (pyautogui, OpenCV, numpy 필요 — main.py와 같은 환경).

import os
import random
import sys
import time

import cv2
import numpy
import pyautogui as gu


# ---------------- 설정 (여기만 고치면 된다) ----------------

# 템플릿: (몹 이름, 파일명). 기병은 제외 — 사용자가 지정한 3종만 노린다.
MOB_TEMPLATES = [
    ('야히의 근위병(데몬)', 'yahi_demon.png'),
    ('야히의 근위병(베레스)', 'yahi_veres.png'),
    ('야히의 근위병(서큐버스)', 'yahi_succubus.png'),
]

CONFIDENCE = 0.85          # main.py MARK_CONF와 같은 값. 낮추면 오탐, 높이면 못 찾음.
SCALES = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]  # main.py MARK_SCALES와 같음 (거리마다 크기 다름).
BOTTOM_CUT = 0.88          # main.py MARK_BOTTOM_CUT와 같음. 화면 아래 12%는 안 본다 (채팅·HP바 오탐 방지).

TURNUNDEAD_KEY = None      # <<< 반드시 턴언데드 단축키로 바꿀 것 (예: 'F1'). None이면 실행 안 됨.
SKILL_FIRST = False        # False: 클릭 -> 키 / True: 키 -> 클릭 (턴언데드 시전 방식에 맞춰 바꿀 것).

CLICK_JITTER = 8           # 클릭 직전 미세 흔들림(px). main.py CLICK_ADJ와 같음.
CLICK_DELAY = (0.04, 0.13)  # 자리 잡고 클릭까지(초). main.py CLICK_DELAY와 같음.
CAST_DELAY = 0.5           # 클릭과 키 입력 사이 대기(초). 타겟 잡히는 시간.
AFTER_CAST_DELAY = 2.0     # 시전 후 다음 스캔까지 대기(초). 캐스팅·쿨다운·몹 소멸 여유.
LOOP_DELAY = 1.0           # 타겟 못 찾았을 때 다음 스캔까지 대기(초).

IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'image')


# ---------------- 유틸 ----------------

def log(msg):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), msg), flush=True)


def load_templates():
    """있는 템플릿만 그레이스케일로 읽는다. 없는 건 로그만 남기고 건너뜀."""
    loaded = []
    for name, fname in MOB_TEMPLATES:
        path = os.path.join(IMAGE_DIR, fname)
        if not os.path.isfile(path):
            log('템플릿 없음, 건너뜀: %s (%s)' % (name, path))
            continue
        tpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            log('템플릿 읽기 실패, 건너뜀: %s' % name)
            continue
        loaded.append((name, tpl))
        log('템플릿 로드: %s (%dx%d)' % (name, tpl.shape[1], tpl.shape[0]))
    return loaded


def screenshot_gray():
    """주 모니터 스크린샷 -> 그레이스케일 numpy 배열."""
    img = gu.screenshot()
    arr = numpy.array(img)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


def find_targets(screen, templates):
    """화면에서 템플릿과 일치하는 위치를 찾는다.
    템플릿·스케일마다 최고점 하나씩만 보고, 겹치는 후보는 높은 점수만 남긴 뒤
    화면 중앙에 가장 가까운 것을 타겟으로 고른다 (플레이어가 화면 중앙 근처라
    중앙에 가까운 몹이 곧 플레이어에게 가까운 몹이다)."""
    h, w = screen.shape[0], screen.shape[1]
    cx, cy = w // 2, h // 2
    cands = []  # (점수, x, y, 몹 이름)
    for name, tpl in templates:
        th, tw = tpl.shape[0], tpl.shape[1]
        for s in SCALES:
            nw, nh = int(tw * s), int(th * s)
            if nw < 1 or nh < 1 or nw > w or nh > h:
                continue
            needle = tpl if s == 1.0 else cv2.resize(tpl, (nw, nh), interpolation=cv2.INTER_CUBIC)
            res = cv2.matchTemplate(screen, needle, cv2.TM_CCOEFF_NORMED)
            _, mx, _, ml = cv2.minMaxLoc(res)
            if mx < CONFIDENCE:
                continue
            x = ml[0] + nw // 2
            y = ml[1] + nh // 2
            if y > h * BOTTOM_CUT:
                continue  # 하단 UI는 안 본다
            cands.append((float(mx), x, y, name))
    if not cands:
        return None
    # 겹치는 후보 제거: 30px 안에 있으면 점수 높은 것만 남긴다
    cands.sort(key=lambda c: -c[0])
    kept = []
    for c in cands:
        if all((c[1] - k[1]) ** 2 + (c[2] - k[2]) ** 2 > 30 * 30 for k in kept):
            kept.append(c)
    # 화면 중앙에 가장 가까운 것을 타겟으로
    kept.sort(key=lambda c: (c[1] - cx) ** 2 + (c[2] - cy) ** 2)
    return kept[0]  # (점수, x, y, 몹 이름)


def click_target(x, y):
    """사람처럼 미세 흔들림 + 짧은 대기 후 클릭."""
    gu.moveTo(x + random.randint(-CLICK_JITTER, CLICK_JITTER),
              y + random.randint(-CLICK_JITTER, CLICK_JITTER))
    time.sleep(random.uniform(*CLICK_DELAY))
    gu.click()


def cast_turnundead():
    """턴언데드 단축키 1회. 길2 함수 호출로 바꿀 때는 이 함수만 바꾸면 된다."""
    gu.press(TURNUNDEAD_KEY)


def run_once(templates):
    """1회: 찾기 -> (클릭/스킬 순서대로) -> 결과 로그. 시전했으면 True."""
    screen = screenshot_gray()
    tgt = find_targets(screen, templates)
    if tgt is None:
        log('타겟 없음 (3종 몹이 화면에 안 보임)')
        return False
    score, x, y, name = tgt
    log('타겟 발견: %s (점수 %.2f, %d,%d)' % (name, score, x, y))
    if SKILL_FIRST:
        cast_turnundead()
        time.sleep(CAST_DELAY)
        click_target(x, y)
    else:
        click_target(x, y)
        time.sleep(CAST_DELAY)
        cast_turnundead()
    log('턴언데드 시전: %s' % name)
    return True


def main():
    if TURNUNDEAD_KEY is None:
        print('TURNUNDEAD_KEY가 비어 있다. turnundead.py 상단에서 턴언데드 단축키로 바꿔라.')
        return
    templates = load_templates()
    if not templates:
        print('템플릿이 하나도 없다. image/ 폴더에 yahi_demon.png 등 3개 중 최소 1개를 넣어라.')
        return
    once = '--once' in sys.argv
    log('시작 (템플릿 %d개, 키=%s, 순서=%s)' % (
        len(templates), TURNUNDEAD_KEY, '키->클릭' if SKILL_FIRST else '클릭->키'))
    try:
        while True:
            casted = run_once(templates)
            if once:
                break
            time.sleep(AFTER_CAST_DELAY if casted else LOOP_DELAY)
    except (KeyboardInterrupt, gu.FailSafeException):
        log('중지됨')
    except Exception as e:
        log('오류: %r' % e)
        raise


if __name__ == '__main__':
    main()
