# sweep_mem.py
#
# sweep.py 메모리 버전 (테스트용). 이미지 매칭 대신 메모리(엔티티 테이블)로 타겟을 찾는다.
#   1. 엔티티 테이블에서 TARGET_NAMES에 해당하는 몹을 찾아 게임 좌표를 읽는다
#   2. 캘리브레이션 아핀(calib.json, turnundead_mem과 공유)이 있으면 그걸로 모니터 좌표로 변환,
#      없으면 게임 창 중심 + 스케일 추정치 (정확도 낮음)
#   3. 각 위치에서 sweep.py와 같은 클릭 시퀀스 (휠클릭 -> 휠 위 -> 클릭 -> 휠 아래)
#
# sweep.py 원본은 건드리지 않는다. 이 파일만 테스트용으로 따로 둔다.
# 같은 폴더에 memread.py + mem.json + turnundead_mem.py가 있어야 한다.
# 실행: python sweep_mem.py

import math
import time

import keyboard as k

import main
from main import gu

import memread as mr
from turnundead_mem import (
    apply_affine,
    game_window_center,
    load_calib,
    raw_to_game,
)

#=====================================================================
# 설정 : 여기만 고치면 된다
#=====================================================================
TARGET_NAMES = [   # 메모리에서 찾을 몹 이름 (정확히 일치). turnundead_mem과 같은 근위병 3종이 기본값.
    '야히의 근위병(데몬)',
    '야히의 근위병(베레스)',
    '야히의 근위병(서큐버스)',
]
CHAR_NAME  = '여포'     # 내 캐릭터 이름 (self 찾기용)
SCALE      = 8.0        # 캘리브레이션 없을 때만 쓰는 스케일 추정치 (px/게임단위). postracker 기본값과 같음.
REPEAT_SEC = 0.5         # 한 바퀴 돌고 쉬는 시간(초)
CLICK_DY   = 0           # 클릭 지점 오프셋(px). 이미지 버전은 50이었는데(매칭된 네임플레이트 아래 몸통을 치기 위해),
                         # 메모리 버전은 아핀이 몹 본체 위치를 직접 주니까 0이 기본값. 빗나가면 여기서 조정.
SETTLE_SEC = 0.1         # 이동 후 클릭까지 대기(초)
WHEEL_GAP  = 0.5         # 클릭 후 휠 이동까지 대기(초)
WHEEL_CLICK_GAP = 1.0    # 휠 이동 후 2번째 클릭까지 대기(초)
STOP_KEY   = 'esc'       # 이 키를 누르면 종료
#=====================================================================

gu.FAILSAFE = True          # 마우스 모서리 탈출 켜둠 (sweep.py와 같게)


class MemScanner(object):
    """memread로 엔티티 테이블을 읽어 TARGET_NAMES 몹의 모니터 좌표를 돌려준다."""

    def __init__(self):
        self.mem = None
        self.err = None
        self.coef = None      # 캘리브레이션 아핀 계수 (없으면 None -> 스케일 추정치)
        self.calib_ok = False

    def attach(self):
        path, found, _tried = mr.findfile('mem.json')
        if not found:
            self.err = 'mem.json을 못 찾음 (스크립트 옆에 mem.json이 있어야 함)'
            return False
        self.mem = mr.Mem(path, lambda s: None)
        if not self.mem.attach(None):
            self.err = '게임 붙기 실패: ' + str(self.mem.err)
            self.mem = None
            return False
        # 캘리브레이션은 시작할 때 한 번만 읽는다. 다시 맞췄으면 스크립트를 재시작할 것.
        _pts, fit = load_calib()
        self.coef = fit
        self.calib_ok = fit is not None
        self.err = None
        return True

    def detach(self):
        if self.mem is not None:
            try:
                self.mem.detach()
            except Exception:
                pass
        self.mem = None

    def scan_all(self):
        """TARGET_NAMES 몹의 모니터 중심 좌표 리스트. 가까운 순으로 정렬한다.
        self를 못 찾거나 타겟이 없으면 빈 리스트."""
        if self.mem is None:
            return []
        objs, _head, _count = self.mem.entity_table()
        self_ent = None
        targets = []
        for o in objs:
            gx, gy = raw_to_game(o['x'], o['y'])
            if o.get('name') == CHAR_NAME and self_ent is None:
                self_ent = {'id': o['id'], 'gx': gx, 'gy': gy}
            if o.get('name') in TARGET_NAMES:
                targets.append({'id': o['id'], 'name': o.get('name'),
                                'gx': gx, 'gy': gy})
        if self_ent is None or not targets:
            return []
        if self.coef is not None:
            for t in targets:
                mx, my = apply_affine(self.coef,
                                      t['gx'] - self_ent['gx'],
                                      t['gy'] - self_ent['gy'])
                t['mon'] = (int(round(mx)), int(round(my)))
        else:
            center = game_window_center()
            if center is None:
                sw, sh = gu.size()
                center = (sw // 2, sh // 2)
            for t in targets:
                mx = center[0] + (t['gx'] - self_ent['gx']) * SCALE
                my = center[1] + (t['gy'] - self_ent['gy']) * SCALE
                t['mon'] = (int(round(mx)), int(round(my)))
        for t in targets:
            t['dist'] = math.hypot(t['gx'] - self_ent['gx'],
                                   t['gy'] - self_ent['gy'])
        targets.sort(key=lambda t: t['dist'])
        return [(t['mon'][0], t['mon'][1]) for t in targets]


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
    """한 위치 공격 : (x, y + CLICK_DY)로 이동 후 휠(중간) 클릭,
    0.5초 뒤 휠 위로 1회, 1초 뒤 클릭, 0.5초 뒤 휠 아래로 1회. (sweep.py와 동일)"""
    tx, ty = x, y + CLICK_DY
    _safemove(tx, ty)
    time.sleep(SETTLE_SEC)
    gu.middleClick()
    main.log('타격 : %d,%d  (휠클릭)' % (tx, ty))
    time.sleep(WHEEL_GAP)
    gu.scroll(1)            # 휠 위로 1회
    time.sleep(WHEEL_CLICK_GAP)
    gu.middleClick()
    time.sleep(WHEEL_GAP)
    gu.scroll(-1)           # 휠 아래로 1회 (원위치)


def repeat():
    """0.5초 간격 반복 : 메모리 스캔 -> 각 위치마다 휠클릭 시퀀스 순차 반복."""
    sc = MemScanner()
    if not sc.attach():
        main.log('sweep_mem 시작 실패 : ' + str(sc.err))
        return
    if sc.calib_ok:
        main.log('sweep_mem 시작 : 메모리 방식 (캘리브레이션 아핀 적용 중, %s초 간격, %s=종료)'
                 % (REPEAT_SEC, STOP_KEY.upper()))
    else:
        main.log('sweep_mem 시작 : 메모리 방식 (캘리브레이션 없음 - 스케일 추정치 %.1f 사용, 정확도 낮음, %s초 간격, %s=종료)'
                 % (SCALE, REPEAT_SEC, STOP_KEY.upper()))
    main.log('타겟 : %s / 내 캐릭터 : %s' % (', '.join(TARGET_NAMES), CHAR_NAME))
    n = 0
    try:
        while True:
            if k.is_pressed(STOP_KEY):
                break
            n += 1
            pts = sc.scan_all()
            if pts:
                main.log('[%d] 메모리 타겟 %d개' % (n, len(pts)))
            for (x, y) in pts:
                if k.is_pressed(STOP_KEY):
                    break
                hit(x, y)
            time.sleep(REPEAT_SEC)
    finally:
        sc.detach()
    main.log('sweep_mem 종료')


if __name__ == '__main__':
    try:
        repeat()
    except KeyboardInterrupt:
        main.log('sweep_mem 종료 (Ctrl+C)')
