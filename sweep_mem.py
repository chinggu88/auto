# sweep_mem.py
#
# sweep.py 메모리 버전 (테스트용). 이미지 매칭을 쓰지 않는다. 마우스도 쓰지 않는다.
#   0. 근처 유닛 중 "마패"가 들어간 캐릭터(플레이어)를 메모리에서 찾는다
#      - 이름에 '마패' 포함 OR 혈맹 ID(+0x44) == 202 (마패 혈맹, 여포도 202로 실측 확인됨)
#      - self(씽씽) 제외, 게임 거리 DIST_MAX 이하, 가까운 순으로 전부 (가장 가까운 1명만 아님)
#   3. 이미지 스캔 없음 (제거됨)
#   4. memcast로 아이언 스킨을 시전한다 (memcast.py, 마우스 클릭 없음).
#      - 매칭되는 혈원 전부를 순서대로(라운드 로빈) 한 명씩 memcast로 쏜다.
#      - 아이언 스킨 스킬 코드 167 (0xA7). 대상 id를 spell_target 메모리에 쓰고,
#        스킬 창에서 '아이언 스킨'이 든 단축키(F5~F12)를 눌러 시전한다. 코드 주입 없음.
#      - 디스패처(skillcast.py) 방식은 self 포인터(DAT_005ab548)가 0으로 읽혀 막혀서,
#        memcast 방식으로 바꿨다 (2026-11-13). self 구조체를 메모리 스캔으로 찾아도
#        엔티티 오브젝트 말고는 안 나와서 디스패처 길은 보류.
#      - 주의: 게임 창이 맨 앞에 있어야 하고, '아이언 스킨'이 단축키(F5~F12)에 있어야 한다.
#   - 모니터 위치(모니터 좌표)는 이제 시전에 안 쓰고 로그 표시용으로만 계산한다.
#     (캘리브레이션은 postracker.py 방식 참조: 허수아비 캘리브레이션 > turnundead_mem calib.json > 스케일.)
#
# sweep.py 원본은 건드리지 않는다. 이 파일만 테스트용으로 따로 둔다.
# 같은 폴더에 memread.py + mem.json + turnundead_mem.py + postracker.py + memcast.py가 있어야 한다.
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
from postracker import load_sc_calib  # postracker 방식 참조: 허수아비 캘리브레이션 우선
import memcast  # memcast 시전 (대상 id 메모리 쓰기 + 단축키, 코드 주입 없음)

#=====================================================================
# 설정 : 여기만 고치면 된다
#=====================================================================
TARGET_NAME_SUBSTR = '마패'  # 이름에 이 단어가 들어가면 매칭
TARGET_CLAN_ID = 202         # 혈맹 ID(+0x44). 202 = 마패 (여포도 202로 실측 확인됨)
SELF_ID      = 1010177       # 실행 캐릭터(씽씽)의 id. self 찾기는 이름이 아니라 id로 한다.
SELF_NAME    = '씽씽'        # 로그 표시용
# (여포 제외 없음 — 모든 혈원에게 버프가 들어가야 해서 제외를 없앰)
DIST_MAX   = 10              # 근처 거리 제한 (게임 단위). 이 안의 마패 캐릭터만 노린다.
SCALE      = 8.0             # 캘리브레이션 없을 때만 쓰는 스케일 추정치 (px/게임단위)
REPEAT_SEC = 0.5             # 한 바퀴 돌고 쉬는 시간(초). 타겟 재스캔 간격.
CAST_SPELL = '아이언 스킨'  # 시전할 마법 이름. 스킬 창 로그(--spells)에 나오는 이름과 같아야 한다 (띄어쓰기는 무시).
CAST_COOLDOWN = 0.5          # 아이언 스킨 시전 간격(초). 스킬 쿨타임 고려해 너무 자주 안 쏨.
                             # 아이언 스킨 쿨다운 테이블 값(0x4915A0+167*2)은 0으로 확인됨 — 쿨다운 게이트 없음.
STOP_KEY   = 'esc'           # 이 키를 누르면 종료
#=====================================================================

gu.FAILSAFE = True          # 마우스 모서리 탈출 켜둠 (sweep.py와 같게)


class MemScanner(object):
    """memread로 엔티티 테이블을 읽어 근처 마패 캐릭터 전부의 모니터 좌표를 돌려준다.
    모니터 위치는 postracker.py 방식: 허수아비 캘리브레이션 > turnundead_mem calib.json > 스케일 추정치."""

    def __init__(self):
        self.mem = None
        self.err = None
        self.coef = None      # 캘리브레이션 아핀 계수 (없으면 None -> 스케일 추정치)
        self.calib_ok = False
        self.calib_src = 'scale'  # 'scarecrow' / 'turnundead' / 'scale'

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
        # postracker.py 방식 참조: 허수아비 캘리브레이션(scarecrow_calib.json) 우선,
        # 없거나 fit 실패면 turnundead_mem calib.json, 둘 다 없으면 스케일 추정치.
        _sc_pts, sc_fit = load_sc_calib()
        if sc_fit is not None:
            self.coef = sc_fit
            self.calib_ok = True
            self.calib_src = 'scarecrow'
        else:
            _pts, fit = load_calib()
            self.coef = fit
            self.calib_ok = fit is not None
            self.calib_src = 'turnundead' if fit is not None else 'scale'
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
            cands.append({'id': o['id'], 'name': name, 'ptr': o.get('ptr'),
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


def cast_at(caster, tgt):
    """아이언 스킨 시전 : memcast로 쏜다 (마우스 안 씀, 코드 주입 없음).
    memcast.Caster가 대상 id를 spell_target 메모리에 쓰고, 스킬 창에서
    '아이언 스킨'이 든 단축키(F5~F12)를 눌러 시전한다.
    돌려주는 res: {'state', 'key', 'msg'}. state == 'sent'면 시전됨."""
    try:
        res = caster.cast(tgt['id'], tgt.get('ptr'), CAST_SPELL, avoid=())
    except Exception as e:
        main.log('아이언 스킨 시전 실패 : id=%s name=%s - 오류: %s'
                 % (tgt['id'], tgt['name'], e))
        return False
    state = res.get('state')
    if state == 'sent':
        main.log('아이언 스킨 시전(memcast) : id=%s name=%s clan=%s dist=%.1f [%s] %s (모니터 %d,%d, %s 매칭)'
                 % (tgt['id'], tgt['name'], tgt['clan'], tgt['dist'],
                    (res.get('key') or '-').upper(), res.get('msg') or '',
                    tgt['x'], tgt['y'], tgt['match_by']))
        return True
    main.log('아이언 스킨 시전 실패 : id=%s name=%s - [%s] %s'
             % (tgt['id'], tgt['name'], state, res.get('msg') or ''))
    return False


def repeat():
    """0.5초 간격 반복 : 마패 혈원 재스캔 -> CAST_COOLDOWN마다 다음 혈원 1명에게 아이언 스킨(memcast).
    혈원 전부를 순서대로(라운드 로빈) 돌아가면서 쏜다. 한 명만 있으면 그 한 명한테만 계속 쏜다.
    마우스는 쓰지 않는다. 게임 창이 맨 앞에 있어야 하고, '아이언 스킨'이 단축키(F5~F12)에 있어야 한다."""
    sc = MemScanner()
    if not sc.attach():
        main.log('sweep_mem 시작 실패 : ' + str(sc.err))
        return
    # memcast 시전용 핸들 (Mem을 그대로 넘긴다. 쓰기 핸들은 처음 시전할 때 연다).
    caster = memcast.Caster(sc.mem)
    if sc.calib_ok:
        calib_name = {'scarecrow': '허수아비 캘리브레이션(postracker)',
                      'turnundead': '캘리브레이션(turnundead_mem)'}[sc.calib_src]
        main.log('sweep_mem 시작 : memcast 방식 (아이언 스킨, %s 아핀은 로그 표시용, %s초 간격, 시전 간격 %s초, %s=종료)'
                 % (calib_name, REPEAT_SEC, CAST_COOLDOWN, STOP_KEY.upper()))
    else:
        main.log('sweep_mem 시작 : memcast 방식 (아이언 스킨, 캘리브레이션 없음 - 스케일 추정치 %.1f는 로그 표시용, %s초 간격, 시전 간격 %s초, %s=종료)'
                 % (SCALE, REPEAT_SEC, CAST_COOLDOWN, STOP_KEY.upper()))
    main.log('타겟 : 이름에 "%s" 포함 또는 혈맹 ID %d / 거리 %d 이하 / 실행 캐릭터 : %s(id %d) / 방식 : 혈원 전부를 순서대로 돌아가며 memcast 시전 (게임 창 맨 앞 + 아이언 스킨 단축키 필요)'
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
                    cast_at(caster, nxt)
                    last_cast_id = nxt['id']
                    last_cast = now
            time.sleep(REPEAT_SEC)
    finally:
        caster.close()
        sc.detach()
    main.log('sweep_mem 종료')


if __name__ == '__main__':
    try:
        repeat()
    except KeyboardInterrupt:
        main.log('sweep_mem 종료 (Ctrl+C)')
