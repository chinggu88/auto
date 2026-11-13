# sweep_mem.py
#
# sweep.py 메모리 버전 (테스트용). 이미지 매칭을 쓰지 않는다.
#   0. 근처 유닛 중 "마패"가 들어간 캐릭터(플레이어)를 메모리에서 찾는다
#      - 이름에 '마패' 포함 OR 혈맹 ID(+0x44) == 202 (마패 혈맹, +0x44 가설 기준)
#      - self(씽씽) 제외, 게임 거리 DIST_MAX 이하, 가까운 순으로 전부 (가장 가까운 1명만 아님)
#   3. 이미지 스캔 없음 (제거됨)
#   4. 타겟 위치를 구하고, 어스바인드 스킬을 그 캐릭터 위치에 사용한다
#      - 매칭되는 혈원 전부를 순서대로(라운드 로빈) 한 명씩 휠클릭 1회로 시전.
#        어스바인드가 휠클릭에 바인딩돼 있어야 함
#      - 스킬 코드(DAT_005fd87c)를 메모리에서 읽어 확인하는 건 확장 예정
#        (휠클릭 방식은 코드가 필요 없어서 지금은 안 읽음. 디스패처로 직접 부르려면 코드 필요)
#
# sweep.py 원본은 건드리지 않는다. 이 파일만 테스트용으로 따로 둔다.
# 같은 폴더에 memread.py + mem.json + turnundead_mem.py가 있어야 한다.
# 실행: python sweep_mem.py

import math
import struct
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
TARGET_NAME_SUBSTR = '마패'  # 이름에 이 단어가 들어가면 매칭
TARGET_CLAN_ID = 202         # 혈맹 ID(+0x44). 202 = 마패 (가설: 개이쁨 0, 씽씽 202)
SELF_ID      = 1010177       # 실행 캐릭터(씽씽)의 id. self 찾기는 이름이 아니라 id로 한다.
SELF_NAME    = '씽씽'        # 로그 표시용
# (여포 제외 없음 — 모든 혈원에게 버프가 들어가야 해서 제외를 없앰)
DIST_MAX   = 10              # 근처 거리 제한 (게임 단위). 이 안의 마패 캐릭터만 노린다.
SCALE      = 8.0             # 캘리브레이션 없을 때만 쓰는 스케일 추정치 (px/게임단위)
REPEAT_SEC = 0.5             # 한 바퀴 돌고 쉬는 시간(초). 타겟 재스캔 간격.
CAST_COOLDOWN = 0.5          # 어스바인드 시전 간격(초). 스킬 쿨타임 고려해 너무 자주 안 쏨.
CLICK_DY   = 0               # 클릭 지점 오프셋(px). 메모리는 몹 본체 위치를 직접 주니까 0.
SETTLE_SEC = 0.1             # 이동 후 클릭까지 대기(초)
STOP_KEY   = 'esc'           # 이 키를 누르면 종료
#=====================================================================

gu.FAILSAFE = True          # 마우스 모서리 탈출 켜둠 (sweep.py와 같게)


class MemScanner(object):
    """memread로 엔티티 테이블을 읽어 근처 마패 캐릭터 1명의 모니터 좌표를 돌려준다."""

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

    def _clan_id(self, ptr):
        """객체 +0x44 혈맹 ID(u32)를 읽는다. 못 읽으면 None.
        entity_table()은 +0x44를 dict에 안 담아서 여기서 직접 읽는다."""
        try:
            data = self.mem.object_bytes(ptr, 0x48)
        except Exception:
            return None
        if data is None or len(data) < 0x48:
            return None
        try:
            return struct.unpack_from('<I', data, 0x44)[0]
        except Exception:
            return None

    def find_targets(self):
        """매칭되는 마패 캐릭터 전부를 가까운 순으로 찾는다.
        돌려주는 것: [{'x','y','id','name','clan','dist','match_by'}, ...] (가까운 순) 또는 [].
        x, y는 모니터 좌표. match_by는 'name'(이름 포함) 또는 'clan'(혈맹 ID)."""
        if self.mem is None:
            return []
        objs, _head, _count = self.mem.entity_table()
        self_ent = None
        cands = []
        for o in objs:
            gx, gy = raw_to_game(o['x'], o['y'])
            if o['id'] == SELF_ID and self_ent is None:
                self_ent = {'id': o['id'], 'gx': gx, 'gy': gy}
        if self_ent is None:
            return []
        for o in objs:
            if o['id'] == self_ent['id']:
                continue  # self(씽씽) 제외
            name = o.get('name')
            match_by = None
            if name and TARGET_NAME_SUBSTR in name:
                match_by = 'name'
            elif o.get('type') == 255:
                # 플레이어만 혈맹 ID로 판별. 몹/NPC는 type이 달라서 제외.
                clan = self._clan_id(o['ptr'])
                if clan == TARGET_CLAN_ID:
                    match_by = 'clan'
            if match_by is None:
                continue
            gx, gy = raw_to_game(o['x'], o['y'])
            dist = math.hypot(gx - self_ent['gx'], gy - self_ent['gy'])
            if dist > DIST_MAX:
                continue
            cands.append({'id': o['id'], 'name': name,
                          'clan': self._clan_id(o['ptr']) if match_by == 'clan' else None,
                          'gx': gx, 'gy': gy, 'dist': dist,
                          'match_by': match_by})
        if not cands:
            return []
        cands.sort(key=lambda t: t['dist'])
        out = []
        for t in cands:
            if self.coef is not None:
                mx, my = apply_affine(self.coef,
                                      t['gx'] - self_ent['gx'],
                                      t['gy'] - self_ent['gy'])
            else:
                center = game_window_center()
                if center is None:
                    sw, sh = gu.size()
                    center = (sw // 2, sh // 2)
                mx = center[0] + (t['gx'] - self_ent['gx']) * SCALE
                my = center[1] + (t['gy'] - self_ent['gy']) * SCALE
            t['x'] = int(round(mx))
            t['y'] = int(round(my))
            out.append(t)
        return out


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


def cast_at(tgt):
    """어스바인드 시전 : 타겟 모니터 위치에 휠(중간) 클릭 1회.
    어스바인드가 휠클릭에 바인딩돼 있어야 한다 (턴언데드 방식과 같음)."""
    tx, ty = tgt['x'], tgt['y'] + CLICK_DY
    _safemove(tx, ty)
    time.sleep(SETTLE_SEC)
    gu.middleClick()
    main.log('어스바인드 시전 : id=%s name=%s clan=%s dist=%.1f -> %d,%d (%s 매칭)'
             % (tgt['id'], tgt['name'], tgt['clan'], tgt['dist'],
                tx, ty, tgt['match_by']))


def repeat():
    """0.5초 간격 반복 : 마패 혈원 재스캔 -> CAST_COOLDOWN마다 다음 혈원 1명에게 어스바인드.
    혈원 전부를 순서대로(라운드 로빈) 돌아가면서 쏜다. 한 명만 있으면 그 한 명한테만 계속 쏜다."""
    sc = MemScanner()
    if not sc.attach():
        main.log('sweep_mem 시작 실패 : ' + str(sc.err))
        return
    if sc.calib_ok:
        main.log('sweep_mem 시작 : 메모리 방식 (캘리브레이션 아핀 적용 중, %s초 간격, 시전 간격 %s초, %s=종료)'
                 % (REPEAT_SEC, CAST_COOLDOWN, STOP_KEY.upper()))
    else:
        main.log('sweep_mem 시작 : 메모리 방식 (캘리브레이션 없음 - 스케일 추정치 %.1f 사용, 정확도 낮음, %s초 간격, 시전 간격 %s초, %s=종료)'
                 % (SCALE, REPEAT_SEC, CAST_COOLDOWN, STOP_KEY.upper()))
    main.log('타겟 : 이름에 "%s" 포함 또는 혈맹 ID %d / 거리 %d 이하 / 실행 캐릭터 : %s(id %d) / 방식 : 혈원 전부를 순서대로 돌아가며 시전'
             % (TARGET_NAME_SUBSTR, TARGET_CLAN_ID, DIST_MAX, SELF_NAME, SELF_ID))
    last_cast = 0.0
    last_cast_id = None
    had_target = False
    try:
        while True:
            if k.is_pressed(STOP_KEY):
                break
            tgts = sc.find_targets()
            if not tgts:
                if had_target:
                    main.log('마패 타겟 사라짐')
                    had_target = False
                    last_cast_id = None
            else:
                if not had_target:
                    main.log('마패 타겟 발견 : %d명 (%s)'
                             % (len(tgts),
                                ', '.join('%s(id %s)' % (t['name'], t['id']) for t in tgts)))
                    had_target = True
                now = time.time()
                if now - last_cast >= CAST_COOLDOWN:
                    # 라운드 로빈 : 지난번에 쏜 혈원 다음 순서부터. 지난번 혈원이 없으면 첫 번째부터.
                    ids = [t['id'] for t in tgts]
                    if last_cast_id is None or last_cast_id not in ids:
                        nxt = tgts[0]
                    else:
                        nxt = tgts[(ids.index(last_cast_id) + 1) % len(tgts)]
                    cast_at(nxt)
                    last_cast_id = nxt['id']
                    last_cast = now
            time.sleep(REPEAT_SEC)
    finally:
        sc.detach()
    main.log('sweep_mem 종료')


if __name__ == '__main__':
    try:
        repeat()
    except KeyboardInterrupt:
        main.log('sweep_mem 종료 (Ctrl+C)')
