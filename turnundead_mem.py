# turnundead_mem.py — 그림자신전 3층 야히의 근위병에게 턴언데드 사용 (메모리 버전, GUI)
#
# 화면 버전(turnundead.py)과 별개 파일이다. 템플릿 이미지가 필요 없고,
# 메모리 엔티티 테이블에서 몹 정보(이름·id·좌표)를 직접 읽어 클릭한다.
# 여러 사람이 쓸 수 있게, 캐릭터명을 입력받아 그 캐릭터를 self 기준으로 삼는다.
#
# 동작: 엔티티 테이블 스캔 -> 입력한 캐릭터명으로 self 찾기 -> 근위병 3종 중
#   self에게 가장 가까운 몹 선택 -> 게임 좌표를 화면 픽셀로 변환(캘리브레이션)
#   -> 좌클릭(타겟) -> 같은 위치 휠클릭(턴언데드) -> 반복
#
# 사용 순서 (게임 실행 중, 게임과 같은 권한(관리자)으로 실행할 것):
#   1. 캐릭터명 입력 (기본값 여포 — 자기 캐릭터명으로 바꿀 것) -> "연결" 클릭
#   2. "새로고침"으로 주변 근위병 목록 확인 (self가 잡히는지, 근위병이 보이는지)
#   3. 캘리브레이션 (최초 1회, PC·해상도마다 따로 해야 함. calib.json에 저장됨):
#      - 목록에서 근위병 하나를 선택하고, 게임에서 그 몹 위에 마우스를 올린 뒤 F9
#      - 서로 떨어진 위치의 몹으로 3번 이상 반복 (많을수록, 넓게 퍼질수록 정확)
#      - 포인트가 3개 이상이고 오차가 작으면 "시작" 가능
#   4. "시작" 클릭 -> 자동 반복. "중지"로 멈춤.
#
# 캘리브레이션 원리: 카메라는 플레이어를 따라가므로, 화면 위치는
#   화면 = M * (몹 게임좌표 - self 게임좌표) + C
#   형태의 아핀 변환이다. (몹, self, 마우스 화면좌표) 쌍을 3개 이상 모아
#   최소제곱으로 M, C를 푼다. 플레이어가 이동해도 self 좌표가 같이 바뀌므로
#   변환이 유지된다. 단, 해상도·화면 배치가 바뀌면 다시 해야 한다.
#
# 주의:
#   - F9는 게임에서 쓰는 키와 겹치면 안 된다. 겹치면 아래 CALIB_HOTKEY를 바꿀 것.
#   - 게임 창이 맨 앞에 있을 때만 클릭이 게임에 닿는다. 시작 전에 게임 창을 포커스할 것.
#   - 클릭 방식이라, 캘리브레이션이 틀리면 엉뚱한 곳을 클릭한다. 시작 전 오차를 확인할 것.
#   - 길2(내부 함수 호출)로 바꾸는 건 힐 함수 사냥이 끝나면 그때. 그때는 act() 안의
#     클릭/휠클릭 부분을 함수 호출로 교체하면 된다.
#   - 메모리 읽기는 읽기 전용이다. 쓰기는 하지 않는다.
#
# Windows 전용 (memread, pyautogui, keyboard, tkinter 필요 — main.py와 같은 환경).
# 이 파일은 게임이 없어도 문법 검사는 되지만, 실제 동작 테스트는 Windows + 게임에서만 된다.

import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import pyautogui as gu

try:
    import keyboard as kb
except Exception:
    kb = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memread as mr


# ---------------- 설정 ----------------

TARGET_NAMES = [
    '야히의 근위병(데몬)',
    '야히의 근위병(베레스)',
    '야히의 근위병(서큐버스)',
]
CALIB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calib.json')
CALIB_HOTKEY = 'F9'        # 캘리브레이션 포인트 추가 키. 게임에서 쓰는 키면 바꿀 것.
MIN_CALIB_POINTS = 3       # 최소 포인트 수 (3개 미만이면 시작 불가)
SKILL_FIRST_DEFAULT = False  # True면 휠클릭 -> 좌클릭 순서

CLICK_JITTER = 8
CLICK_DELAY = (0.04, 0.13)
CAST_DELAY = 0.5
AFTER_CAST_DELAY = 2.0
LOOP_DELAY = 1.0


# ---------------- 좌표·캘리브레이션 (순수 계산, numpy 불필요) ----------------

def raw_to_game(rx, ry):
    """엔티티 테이블 raw 좌표 -> 게임 좌표. x는 (raw+32768)/2, y는 raw 그대로."""
    return ((rx & 0xFFFF) + 32768) // 2, ry


def _solve3(a, b):
    """3x3 선형연립 a*x=b를 가우스 소거로 푼다. 특이행렬이면 None."""
    n = 3
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-9:
            return None
        m[col], m[piv] = m[piv], m[col]
        d = m[col][col]
        m[col] = [v / d for v in m[col]]
        for r in range(n):
            if r != col and m[r][col] != 0:
                f = m[r][col]
                m[r] = [v - f * w for v, w in zip(m[r], m[col])]
    return [m[i][n] for i in range(n)]


def fit_affine(points):
    """points: (dx, dy, sx, sy) 리스트. 화면 = M*(dx,dy)+C 를 최소제곱으로 푼다.
    돌려주는 것: (a, b, c, d, e, f, 평균오차px) 또는 None (3개 미만/공선/특이)."""
    if len(points) < 3:
        return None
    # 정규방정식: [sum dx*dx, sum dx*dy, sum dx; ...] * [a,b,c] = [sum dx*sx, ...]
    sxx = sxy = sx_ = syy = sy_ = n = 0
    tx = ty = 0
    sxs = sys_ = 0
    dxs = dys = 0
    for dx, dy, sx, sy in points:
        sxx += dx * dx
        sxy += dx * dy
        sx_ += dx
        syy += dy * dy
        sy_ += dy
        n += 1
        dxs += dx * sx
        dys += dy * sx
        tx += sx
        sxs += dx * sy
        sys_ += dy * sy
        ty += sy
    mat = [[sxx, sxy, sx_], [sxy, syy, sy_], [sx_, sy_, n]]
    coef_x = _solve3(mat, [dxs, dys, tx])
    coef_y = _solve3(mat, [sxs, sys_, ty])
    if coef_x is None or coef_y is None:
        return None
    a, b, c = coef_x
    d, e, f = coef_y
    errs = []
    for dx, dy, sx, sy in points:
        px = a * dx + b * dy + c
        py = d * dx + e * dy + f
        errs.append(math.hypot(px - sx, py - sy))
    return (a, b, c, d, e, f, sum(errs) / len(errs))


def apply_affine(coef, dx, dy):
    a, b, c, d, e, f = coef[:6]
    return a * dx + b * dy + c, d * dx + e * dy + f


def load_calib():
    try:
        with open(CALIB_FILE, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        pts = [(float(p[0]), float(p[1]), float(p[2]), float(p[3]))
               for p in data.get('points', [])]
        fit = fit_affine(pts)
        return pts, fit
    except Exception:
        return [], None


def save_calib(points):
    with open(CALIB_FILE, 'w', encoding='utf-8') as fh:
        json.dump({'points': points}, fh, ensure_ascii=False, indent=1)


# ---------------- 메모리 스캔 ----------------

class Scanner(object):
    """memread.Mem을 감싼 스캔기. 엔티티 테이블에서 self와 근위병을 찾는다."""

    def __init__(self):
        self.mem = None
        self.err = None

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
        self.err = None
        return True

    def detach(self):
        if self.mem is not None:
            try:
                self.mem.detach()
            except Exception:
                pass
        self.mem = None

    def scan(self, char_name):
        """돌려주는 것: (self_dict 또는 None, 근위병 리스트, 전체 이름 목록).
        self_dict/근위병 항목: {'id','ptr','gx','gy','name'} (gx, gy는 게임 좌표)."""
        if self.mem is None:
            return None, [], []
        objs, _head, _count = self.mem.entity_table()
        self_ent = None
        guards = []
        names = set()
        for o in objs:
            gx, gy = raw_to_game(o['x'], o['y'])
            ent = {'id': o['id'], 'ptr': o['ptr'], 'gx': gx, 'gy': gy,
                   'name': o.get('name')}
            if o.get('name'):
                names.add(o['name'])
            if o.get('name') == char_name and self_ent is None:
                self_ent = ent
            if o.get('name') in TARGET_NAMES:
                guards.append(ent)
        if self_ent is not None:
            for g in guards:
                g['dist'] = math.hypot(g['gx'] - self_ent['gx'],
                                       g['gy'] - self_ent['gy'])
            guards.sort(key=lambda g: g['dist'])
        return self_ent, guards, sorted(names)


# ---------------- 작업 스레드 ----------------

class Worker(threading.Thread):
    def __init__(self, scanner, char_name, calib_coef, skill_first, logq):
        super(Worker, self).__init__(daemon=True)
        self.scanner = scanner
        self.char_name = char_name
        self.coef = calib_coef
        self.skill_first = skill_first
        self.logq = logq
        self.stop_flag = threading.Event()
        self.latest = None  # (self_ent, guards) — GUI 캘리브레이션용, lock으로 보호
        self.latest_lock = threading.Lock()

    def log(self, msg):
        self.logq.put(msg)

    def _click(self, x, y):
        import random
        gu.moveTo(x + random.randint(-CLICK_JITTER, CLICK_JITTER),
                  y + random.randint(-CLICK_JITTER, CLICK_JITTER))
        time.sleep(random.uniform(*CLICK_DELAY))
        gu.click()

    def _wheel(self, x, y):
        import random
        gu.moveTo(x + random.randint(-CLICK_JITTER, CLICK_JITTER),
                  y + random.randint(-CLICK_JITTER, CLICK_JITTER))
        time.sleep(random.uniform(*CLICK_DELAY))
        gu.click(button='middle')

    def _act(self, tgt, self_ent):
        dx = tgt['gx'] - self_ent['gx']
        dy = tgt['gy'] - self_ent['gy']
        fx, fy = apply_affine(self.coef, dx, dy)
        sw, sh = gu.size()
        ix, iy = int(round(fx)), int(round(fy))
        if not (0 <= ix < sw and 0 <= iy < sh):
            self.log('타겟 화면좌표가 화면 밖(%d,%d)이라 건너뜀: %s' % (ix, iy, tgt['name']))
            return False
        self.log('타겟: %s id %d (게임 %d,%d -> 화면 %d,%d)' % (
            tgt['name'], tgt['id'], tgt['gx'], tgt['gy'], ix, iy))
        if self.skill_first:
            self._wheel(ix, iy)
            time.sleep(CAST_DELAY)
            self._click(ix, iy)
        else:
            self._click(ix, iy)
            time.sleep(CAST_DELAY)
            self._wheel(ix, iy)
        self.log('턴언데드 시전(휠클릭): %s' % tgt['name'])
        return True

    def run(self):
        self.log('작업 시작 (캐릭터: %s)' % self.char_name)
        while not self.stop_flag.is_set():
            try:
                self_ent, guards, _names = self.scanner.scan(self.char_name)
                with self.latest_lock:
                    self.latest = (self_ent, guards)
                if self_ent is None:
                    self.log('self를 못 찾음 (캐릭터명 확인: %s)' % self.char_name)
                    self.stop_flag.wait(LOOP_DELAY)
                    continue
                if not guards:
                    self.log('주변에 근위병 3종이 안 보임')
                    self.stop_flag.wait(LOOP_DELAY)
                    continue
                tgt = guards[0]
                casted = self._act(tgt, self_ent)
                self.stop_flag.wait(AFTER_CAST_DELAY if casted else LOOP_DELAY)
            except Exception as e:
                self.log('오류: %r' % (e,))
                self.stop_flag.wait(LOOP_DELAY)
        self.log('작업 중지됨')


# ---------------- GUI ----------------

class App(object):
    def __init__(self, root):
        self.root = root
        self.root.title('턴언데드 (메모리 버전)')
        self.scanner = Scanner()
        self.logq = queue.Queue()
        self.worker = None
        self.points, self.fit = load_calib()
        self.coef = self.fit[:6] if self.fit else None

        frm = ttk.Frame(root, padding=10)
        frm.grid(row=0, column=0, sticky='nsew')
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        # 캐릭터명
        ttk.Label(frm, text='캐릭터명:').grid(row=0, column=0, sticky='w')
        self.name_var = tk.StringVar(value='여포')
        ttk.Entry(frm, textvariable=self.name_var, width=20).grid(row=0, column=1, sticky='w')
        ttk.Button(frm, text='연결', command=self.on_connect).grid(row=0, column=2)
        self.self_label = ttk.Label(frm, text='미연결')
        self.self_label.grid(row=0, column=3, sticky='w', padx=8)

        # 근위병 목록
        ttk.Label(frm, text='주변 근위병 (가까운 순):').grid(row=1, column=0, sticky='w', pady=(8, 0))
        self.guard_list = tk.Listbox(frm, height=6, width=70)
        self.guard_list.grid(row=2, column=0, columnspan=4, sticky='ew')
        ttk.Button(frm, text='새로고침', command=self.on_refresh).grid(row=3, column=0, pady=4)

        # 캘리브레이션
        cal = ttk.LabelFrame(frm, text='캘리브레이션', padding=6)
        cal.grid(row=4, column=0, columnspan=4, sticky='ew', pady=6)
        self.cal_label = ttk.Label(cal, text='')
        self.cal_label.grid(row=0, column=0, sticky='w')
        ttk.Label(cal, text='방법: 목록에서 근위병을 선택하고, 게임에서 그 몹 위에 마우스를 올린 뒤 %s를 누른다. 서로 떨어진 위치에서 3번 이상 반복.' % CALIB_HOTKEY, wraplength=520, justify='left').grid(row=1, column=0, sticky='w')
        ttk.Button(cal, text='포인트 초기화', command=self.on_clear_calib).grid(row=2, column=0, sticky='w', pady=4)
        self._refresh_cal_label()

        # 실행
        self.skill_first_var = tk.BooleanVar(value=SKILL_FIRST_DEFAULT)
        ttk.Checkbutton(frm, text='휠클릭 먼저 (기본: 좌클릭 -> 휠클릭)',
                        variable=self.skill_first_var).grid(row=5, column=0, columnspan=2, sticky='w')
        self.start_btn = ttk.Button(frm, text='시작', command=self.on_start)
        self.start_btn.grid(row=5, column=2)
        ttk.Button(frm, text='중지', command=self.on_stop).grid(row=5, column=3)
        self.status_label = ttk.Label(frm, text='대기 중')
        self.status_label.grid(row=6, column=0, columnspan=4, sticky='w', pady=4)

        # 로그
        self.log_text = tk.Text(frm, height=12, width=80, state='disabled')
        self.log_text.grid(row=7, column=0, columnspan=4, sticky='nsew')
        ttk.Button(frm, text='로그 지우기', command=self.on_clear_log).grid(row=8, column=0, pady=4)

        # F9 핫키 (키보드 라이브러리가 있을 때만)
        self.hotkey_ok = False
        if kb is not None:
            try:
                kb.add_hotkey(CALIB_HOTKEY, self._on_calib_hotkey)
                self.hotkey_ok = True
            except Exception as e:
                self.log('핫키 등록 실패(%s): %s 키를 쓸 수 없음' % (CALIB_HOTKEY, e))
        else:
            self.log('keyboard 라이브러리가 없어 F9 캘리브레이션을 쓸 수 없음')

        self.root.after(200, self._poll)
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    # ---------- GUI 헬퍼 ----------

    def log(self, msg):
        self.logq.put('[%s] %s' % (time.strftime('%H:%M:%S'), msg))

    def _refresh_cal_label(self):
        n = len(self.points)
        if self.fit:
            self.cal_label.config(text='포인트 %d개, 평균오차 %.1fpx (시작 가능)' % (n, self.fit[6]))
        else:
            self.cal_label.config(text='포인트 %d개 (최소 %d개 필요, 시작 불가)' % (n, MIN_CALIB_POINTS))

    # ---------- 버튼 ----------

    def on_connect(self):
        if self.scanner.mem is None:
            if not self.scanner.attach():
                self.self_label.config(text='연결 실패')
                self.log('연결 실패: ' + str(self.scanner.err))
                return
            self.log('게임에 붙음')
        self.on_refresh()

    def on_refresh(self):
        if self.scanner.mem is None:
            self.log('먼저 연결을 눌러 게임에 붙을 것')
            return
        name = self.name_var.get().strip()
        if not name:
            self.log('캐릭터명을 입력할 것')
            return
        self_ent, guards, names = self.scanner.scan(name)
        if self_ent is None:
            self.self_label.config(text='self 못 찾음')
            self.log('self 못 찾음: "%s" 이름의 엔티티가 테이블에 없음 (주변 이름: %s)' % (
                name, ', '.join(names[:10]) if names else '없음'))
        else:
            self.self_label.config(text='self: %s id %d (%d,%d)' % (
                name, self_ent['id'], self_ent['gx'], self_ent['gy']))
        self.guard_list.delete(0, 'end')
        for g in guards:
            self.guard_list.insert('end', '%s id %d (%d,%d) 거리 %.0f' % (
                g['name'], g['id'], g['gx'], g['gy'], g.get('dist', 0)))
        if self.worker is not None:
            with self.worker.latest_lock:
                self.worker.latest = (self_ent, guards)

    def _on_calib_hotkey(self):
        # 키보드 훅 스레드에서 실행됨 — tkinter를 직접 건드리지 않고 큐로 넘긴다.
        self.logq.put('__CALIB__')

    def _do_calib_point(self):
        sel = self.guard_list.curselection()
        if not sel:
            self.log('캘리브레이션: 목록에서 근위병을 먼저 선택할 것')
            return
        idx = sel[0]
        # 최신 스캔에서 같은 순서의 근위병을 찾는다 (새로고침 이후 목록 기준)
        name = self.name_var.get().strip()
        self_ent, guards, _names = self.scanner.scan(name)
        if self_ent is None:
            self.log('캘리브레이션: self를 못 찾음')
            return
        if idx >= len(guards):
            self.log('캘리브레이션: 선택한 몹이 최신 스캔에 없음 (새로고침 후 다시 선택)')
            return
        tgt = guards[idx]
        mx, my = gu.position()
        dx = tgt['gx'] - self_ent['gx']
        dy = tgt['gy'] - self_ent['gy']
        self.points.append((float(dx), float(dy), float(mx), float(my)))
        self.fit = fit_affine(self.points)
        self.coef = self.fit[:6] if self.fit else None
        try:
            save_calib(self.points)
        except Exception as e:
            self.log('calib.json 저장 실패: %r' % (e,))
        self.log('포인트 추가: %s (dx %d, dy %d -> 화면 %d,%d), 총 %d개' % (
            tgt['name'], dx, dy, mx, my, len(self.points)))
        self._refresh_cal_label()

    def on_clear_calib(self):
        self.points = []
        self.fit = None
        self.coef = None
        try:
            if os.path.isfile(CALIB_FILE):
                os.remove(CALIB_FILE)
        except Exception:
            pass
        self._refresh_cal_label()
        self.log('캘리브레이션 초기화됨')

    def on_start(self):
        if self.worker is not None and self.worker.is_alive():
            self.log('이미 실행 중')
            return
        if self.scanner.mem is None:
            self.log('먼저 연결을 눌러 게임에 붙을 것')
            return
        if self.coef is None:
            self.log('캘리브레이션 필요: 포인트 %d개 (최소 %d개)' % (
                len(self.points), MIN_CALIB_POINTS))
            return
        if self.fit and self.fit[6] > 50:
            self.log('경고: 캘리브레이션 평균오차가 큼 (%.1fpx). 포인트를 더 찍거나 다시 할 것' % self.fit[6])
        name = self.name_var.get().strip()
        if not name:
            self.log('캐릭터명을 입력할 것')
            return
        self.worker = Worker(self.scanner, name, self.coef,
                             self.skill_first_var.get(), self.logq)
        self.worker.start()
        self.status_label.config(text='실행 중')
        self.log('시작됨 (순서: %s)' % (
            '휠클릭->좌클릭' if self.skill_first_var.get() else '좌클릭->휠클릭'))

    def on_stop(self):
        if self.worker is not None:
            self.worker.stop_flag.set()
            self.worker = None
        self.status_label.config(text='대기 중')
        self.log('중지 요청됨')

    def on_clear_log(self):
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

    def on_close(self):
        self.on_stop()
        if kb is not None:
            try:
                kb.unhook_all()
            except Exception:
                pass
        self.scanner.detach()
        self.root.destroy()

    def _poll(self):
        # __CALIB__ 마커는 F9 핫키 스레드에서 온 캘리브레이션 포인트 요청이다.
        try:
            while True:
                msg = self.logq.get_nowait()
                if msg == '__CALIB__':
                    self._do_calib_point()
                    continue
                self.log_text.configure(state='normal')
                self.log_text.insert('end', msg + '\n')
                self.log_text.see('end')
                self.log_text.configure(state='disabled')
        except queue.Empty:
            pass
        self.root.after(200, self._poll)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
