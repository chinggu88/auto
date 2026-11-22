# autocalib.py — 화면 보정 자동화 (허수아비 F9 보정을 대신한다)
#
# 사용법 :
#   python autocalib.py            게임에 붙어 자동 보정을 한 번 돌리고 auto_calib.json 에 저장
#   main.py 는 시작할 때 '자동 보정' 이 켜져 있으면 이 모듈의 run() 을 부른다
#
# 하는 일 :
#   허수아비 보정은 "이 허수아비(게임 좌표)가 화면 이 자리" 짝을 사람이 F9 로 찍어 모은다.
#   여기서는 그 짝을 커서 아래 엔티티 칸(mem.json chains.hover_id, Lin.exe+0x1AB548 -
#   커서 아래 엔티티의 주소, 빈 땅이면 0)으로 스스로 모은다.
#     1. 게임 창의 실제 그림 영역(제목줄 / 테두리 뺀 곳)을 Windows 에 묻는다
#     2. 그 안을 가운데(내 캐릭터)부터 바깥으로 GRID px 간격으로 커서를 옮기며 hover_id 를 읽는다
#        (두 번 읽어 같을 때만 믿는다 - 커서를 옮긴 직후에는 이전 자리 값이 남아 있을 수 있다)
#     3. 걸린 엔티티의 그 순간 게임 좌표 - 내 좌표 = (dx, dy) 와 커서 화면 좌표를 짝으로 모은다
#        엔티티 + 칸 별로 모은 커서 자리의 가운데를 한 점으로 쓴다 (몹 그림 한가운데)
#     4. 점이 모이면 RANSAC(세 점씩 풀어 가장 많이 맞는 답)으로 아핀을 풀고,
#        아직 못 걸린 엔티티는 예상 자리 둘레만 확인해서 점을 늘린다
#     5. 한 점씩 빼고 풀어 그 점을 맞히는지(LOO) 본 뒤 통과하면 auto_calib.json 에 저장
#   몹 / NPC / 다른 캐릭터 / 나 자신 무엇이든 된다. 허수아비가 없어도 된다.
#   돌리는 동안 마우스를 만지지 말고, 캐릭터를 움직이지 말 것 (몹은 움직여도 그 순간 좌표로 잰다).
#   메모리는 읽기만 한다. 커서를 옮기기만 하고 클릭 / 키 입력은 하지 않는다.

import json
import math
import os
import random
import sys
import time

APP_DIR   = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, 'frozen', False) else __file__))
OUT_FILE  = 'auto_calib.json'
WIN_TITLE = 'Lineage Windows Client'

GRID       = 24      #훑을 때 칸 간격(px). 엔티티 그림보다 작아야 사이로 빠지지 않는다
SETTLE     = 0.03    #커서를 옮긴 뒤 게임이 hover 칸을 갱신할 때까지 기다리는 시간(초)
BUDGET     = 90.0    #전체 최대 시간(초)
NEED_ENTS  = 6       #서로 다른 엔티티 자리가 이만큼 모이면 훑기를 멈추고 확인 단계로 간다
MIN_POINTS = 4       #저장하려면 최소 이만큼의 점 (RANSAC 에서 살아남은 것)
INLIER_PX  = 40      #RANSAC 에서 '맞는 점' 으로 보는 오차(px). 그림 한가운데 추정이라 넉넉히
LOO_MAX    = 30      #한 점씩 빼고 풀었을 때 평균 오차가 이보다 크면 저장하지 않는다
VERIFY_NEAR = [(0, 0), (0, -GRID), (0, GRID), (-GRID, 0), (GRID, 0),
               (-GRID, -GRID), (GRID, -GRID), (-GRID, GRID), (GRID, GRID),
               (0, -2 * GRID), (0, 2 * GRID)]   #확인 단계 : 예상 자리 둘레 (그림은 발보다 위로 크다)
ENT_REFRESH = 0.3    #엔티티 표를 다시 읽는 간격(초). 몹이 움직이므로 걸린 순간 근처의 좌표를 쓴다


def _say(msg):
    print(msg)


#게임 창의 그림 영역 (왼, 위, 너비, 높이) - 모니터 좌표. 못 찾으면 None
def clientrect():
    try:
        import win32gui
    except ImportError:
        return None
    hwnd = win32gui.FindWindow(None, WIN_TITLE)
    if not hwnd:
        return None
    l, t, r, b = win32gui.GetClientRect(hwnd)
    x, y = win32gui.ClientToScreen(hwnd, (0, 0))
    if r - l <= 0 or b - t <= 0:
        return None
    return (x, y, r - l, b - t)


def _move(x, y):
    import win32api
    win32api.SetCursorPos((int(x), int(y)))


#아핀 최소제곱 (turnundead_mem.fit_affine_nocheck 와 같은 식. 그 모듈은 GUI 를 같이 불러와서 따로 둔다)
#  화면x = a*dx + b*dy + c,  화면y = d*dx + e*dy + f
def _solve3(m, v):
    m = [row[:] + [v[i]] for i, row in enumerate(m)]
    for c in range(3):
        piv = max(range(c, 3), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-9:
            return None
        m[c], m[piv] = m[piv], m[c]
        for r in range(3):
            if r != c:
                k = m[r][c] / m[c][c]
                for j in range(c, 4):
                    m[r][j] -= k * m[c][j]
    return [m[i][3] / m[i][i] for i in range(3)]

def _fit(pts):
    if len(pts) < 3:
        return None
    sxx = sxy = sx = syy = sy = n = 0.0
    bx = [0.0, 0.0, 0.0]
    by = [0.0, 0.0, 0.0]
    for dx, dy, X, Y in pts:
        sxx += dx * dx; sxy += dx * dy; sx += dx; syy += dy * dy; sy += dy; n += 1
        bx[0] += dx * X; bx[1] += dy * X; bx[2] += X
        by[0] += dx * Y; by[1] += dy * Y; by[2] += Y
    mat = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, n]]
    cx = _solve3(mat, bx)
    cy = _solve3(mat, by)
    if cx == None or cy == None:
        return None
    return (cx[0], cx[1], cx[2], cy[0], cy[1], cy[2])


def _err(coef, p):
    a, b, c, d, e, f = coef[:6]
    return math.hypot(a * p[0] + b * p[1] + c - p[2], d * p[0] + e * p[1] + f - p[3])


#RANSAC : 세 점씩 풀어 INLIER_PX 안에 드는 점이 가장 많은 답을 고르고 그 점들로 다시 푼다
def fitrobust(pts):
    n = len(pts)
    if n < 3:
        return None, []
    if n <= 12:
        import itertools
        trios = itertools.combinations(range(n), 3)
    else:
        trios = (random.sample(range(n), 3) for _ in range(400))
    best = None
    for tri in trios:
        coef = _fit([pts[i] for i in tri])
        if coef == None:
            continue
        ins = [p for p in pts if _err(coef, p) <= INLIER_PX]
        if best == None or len(ins) > len(best):
            best = ins
    if best == None or len(best) < 3:
        return None, []
    coef = _fit(best)
    if coef == None:
        return None, []
    return coef, [p for p in pts if _err(coef, p) <= INLIER_PX]


#한 점씩 빼고 풀어 그 점을 얼마나 맞히나 (평균 px). 못 풀면 None
def looerr(pts):
    errs = []
    for i in range(len(pts)):
        sub = pts[:i] + pts[i + 1:]
        coef = _fit(sub)
        if coef == None:
            return None
        errs.append(_err(coef, pts[i]))
    return sum(errs) / len(errs) if errs else None


#가운데에서 바깥으로 GRID 간격 네모 둘레 (rect 안만)
def _spiral(cx, cy, rect):
    l, t, w, h = rect
    rmax = max(w, h) // GRID + 1
    for r in range(0, rmax):
        if r == 0:
            ring = [(0, 0)]
        else:
            ring = []
            for i in range(-r, r + 1):
                ring += [(i, -r), (i, r)]
            for j in range(-r + 1, r):
                ring += [(-r, j), (r, j)]
        for i, j in ring:
            x, y = cx + i * GRID, cy + j * GRID
            if l + 2 <= x < l + w - 2 and t + 2 <= y < t + h - 2:
                yield x, y


class _Ents:
    """엔티티 표를 ENT_REFRESH 마다 다시 읽어 ptr -> 게임 좌표 로 들고 있는다"""

    def __init__(self, mem):
        self.mem  = mem
        self.at   = 0.0
        self.pos  = {}
        self.me   = None

    def get(self):
        now = time.perf_counter()
        if now - self.at >= ENT_REFRESH or self.me == None:
            ents, head, count = self.mem.entity_table()
            me  = self.mem.selfent(ents) if ents else None
            pos = {}
            for o in ents or []:
                if o.get('ptr'):
                    pos[o['ptr']] = self.mem.entpos(o)
            mypos = self.mem.selfpos()
            if mypos == None and me != None:
                mypos = self.mem.entpos(me)
            self.pos = pos
            self.me  = mypos
            self.at  = now
        return self.pos, self.me


#자동 보정. 성공하면 (points, coef, 설명), 실패하면 (None, None, 이유)
#  mem   : 붙어 있는 memread.Mem (chains.hover_id 가 있어야 한다)
#  log   : 한 줄 로그 함수
#  alive : 중간에 멈출지 묻는 함수 (False 를 돌려주면 그만둔다). None 이면 끝까지
def run(mem, log=_say, alive=None):
    if mem == None:
        return None, None, '메모리에 안 붙음'
    if mem.value('hover_id') == None:
        return None, None, 'mem.json chains.hover_id 를 못 읽음 (python memprobe.py --hover 로 찾아 넣을 것)'
    rect = clientrect()
    if rect == None:
        return None, None, '게임 창(' + WIN_TITLE + ')을 못 찾음'
    ents = _Ents(mem)
    pos, me = ents.get()
    if me == None:
        return None, None, '내 좌표를 못 읽음'
    if len(pos) < 2:
        return None, None, '주변 엔티티가 없음 (몹 / NPC / 다른 캐릭터가 화면에 몇 개 있어야 한다)'

    log('자동 보정 시작 : 게임 그림 영역 ' + str(rect) + ', 주변 엔티티 ' + str(len(pos)) + '개. 마우스를 만지지 마세요')
    samples = {}   #(ptr, dx, dy) -> [(x, y), ...]
    t0      = time.perf_counter()

    def probe(x, y):
        _move(x, y)
        time.sleep(SETTLE)
        h = mem.value('hover_id')
        if not h:
            return None
        time.sleep(SETTLE)
        if mem.value('hover_id') != h:
            return None
        p, m = ents.get()
        if h not in p or m == None:
            return None
        key = (h, p[h][0] - m[0], p[h][1] - m[1])
        samples.setdefault(key, []).append((x, y))
        return key

    def points():
        out = []
        for (h, dx, dy), xy in samples.items():
            out.append((float(dx), float(dy),
                        sum(q[0] for q in xy) / len(xy), sum(q[1] for q in xy) / len(xy)))
        return out

    def stop():
        return (alive != None and not alive()) or time.perf_counter() - t0 > BUDGET

    #1) 가운데(내 캐릭터)부터 훑는다. 서로 다른 자리가 NEED_ENTS 개 모이고 아핀이 풀리면 그만
    cx, cy = rect[0] + rect[2] // 2, rect[1] + rect[3] // 2
    coef = None
    n = 0
    for x, y in _spiral(cx, cy, rect):
        if stop():
            break
        probe(x, y)
        n += 1
        if n % 50 == 0 and len(samples) >= NEED_ENTS:
            coef, ins = fitrobust(points())
            if coef != None and len(ins) >= NEED_ENTS:
                break
    log('  훑기 : ' + str(n) + '자리, 걸린 엔티티 자리 ' + str(len(samples)) + '개 (' + str(round(time.perf_counter() - t0, 1)) + '초)')

    #2) 확인 : 아직 안 걸린 엔티티를 예상 자리 둘레에서 찾아 점을 늘린다 (멀리 있는 것까지 맞도록)
    coef, ins = fitrobust(points())
    if coef != None:
        p, m = ents.get()
        seen = set(k[0] for k in samples)
        for ptr, gp in list(p.items()):
            if stop() or ptr in seen:
                continue
            dx, dy = gp[0] - m[0], gp[1] - m[1]
            a, b, c, d, e, f = coef[:6]
            px, py = a * dx + b * dy + c, d * dx + e * dy + f
            if not (rect[0] <= px < rect[0] + rect[2] and rect[1] <= py < rect[1] + rect[3]):
                continue
            for ox, oy in VERIFY_NEAR:
                k = probe(px + ox, py + oy)
                if k != None and k[0] == ptr:
                    #같은 엔티티 그림 위를 조금 더 찍어 가운데를 잡는다
                    for ox2, oy2 in VERIFY_NEAR[1:5]:
                        probe(px + ox + ox2 // 2, py + oy + oy2 // 2)
                    break

    #3) 최종 풀이 + 검사
    pts = points()
    coef, ins = fitrobust(pts)
    _move(cx, cy)        #커서를 내 캐릭터 위에 돌려 놓는다
    took = str(round(time.perf_counter() - t0, 1)) + '초'
    if coef == None or len(ins) < MIN_POINTS:
        return None, None, '점이 모자람 (' + str(len(ins)) + ' / ' + str(MIN_POINTS) + '개, ' + took + ') - 화면에 엔티티가 더 있는 곳에서 다시'
    loo = looerr(ins)
    if loo == None or loo > LOO_MAX:
        return None, None, '검사 실패 (한 점 빼고 풀기 평균 오차 ' + str(None if loo == None else round(loo, 1)) + 'px > ' + str(LOO_MAX) + ')'
    why = str(len(ins)) + '점, 평균 오차 ' + str(round(loo, 1)) + 'px, ' + took
    return ins, coef, why


#점을 auto_calib.json 에 저장 (main.loadcalib / postracker 와 같은 'points' 형식)
def save(points, rect=None):
    path = os.path.join(APP_DIR, OUT_FILE)
    f = open(path, 'w', encoding='utf-8')
    json.dump({'points': [list(p) for p in points], 'rect': list(rect) if rect else None,
               'time': time.strftime('%Y-%m-%d %H:%M:%S')}, f)
    f.close()
    return path


def main():
    import memread as mr
    path, ok, tried = mr.findfile('mem.json')
    m = mr.Mem(path, _say)
    if not m.attach():
        _say('게임에 못 붙음 : ' + str(m.err))
        return
    try:
        pts, coef, why = run(m)
        if pts == None:
            _say('자동 보정 실패 : ' + why)
            return
        out = save(pts, clientrect())
        _say('자동 보정 완료 : ' + why)
        _say('저장 : ' + out)
    finally:
        m.detach()


if __name__ == '__main__':
    main()
