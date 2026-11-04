# postracker.py — 내 캐릭터 위치 실시간 추적 GUI (진단용)
# 사용법: repo 폴더에서 python postracker.py
#   (memread.py + mem.json + turnundead_mem.py가 같은 폴더에 있어야 함)
# 첫 줄: 내 캐릭터(기본 여포)의 모니터 위치를 실시간으로 표시한다 (게임 좌표 아님).
#   (sweep 중심/방향이 맞는지 눈으로 확인하는 용도. 휠클릭 체크박스로 클릭도 가능.)
# 아래: 게임 창 중심 vs 모니터 중심, 근위병 리스트 (모니터 위치, 가까운 순).
#   - 움직이는 근위병: 굵은 검은색. 움직이지 않는 근위병: 회색.
#   - '움직이는' = 최근 1초 안에 위치가 바뀐 것 (0.1초 폴링이라 한 번 스텝만으로는
#     깜빡거려서, 움직인 뒤 1초간 굵은색을 유지한다. 첫 발견은 회색.)
# 모니터 위치 계산:
#   - calib.json이 있으면 turnundead_mem의 캘리브레이션(아핀)으로 정확한 화면 좌표.
#     (아핀은 상대 게임 좌표(몹-self) -> 절대 화면 좌표. self = 아핀(0,0).)
#   - calib.json이 없으면 스케일(기본 8px/게임단위, GUI에서 조절)로 추정치 계산:
#     몹 모니터 위치 = 게임 창 중심 + (몹 게임 좌표 - self 게임 좌표) * 스케일.
#     추정치라 화면의 실제 몹 위치와 다를 수 있다. 스케일 값을 바꿔가며 맞춘다.
#     F9 캘리브레이션(turnundead_mem)을 한 번 하면 정확한 모니터 위치가 나온다.
# 폴링: 백그라운드 스레드가 0.1초마다 테이블을 읽고, GUI는 큐로 받아 표시한다.
# 휠클릭 (체크박스로 켤 것, 기본 꺼짐): 움직이는 몹 중 게임 거리 10 이하인 것을
# 가까운 순으로, 2초 쿨타임마다 1마리씩 모니터 위치에 휠클릭한다.
# 클릭 위치는 calib이 있으면 정확한 아핀 위치, 없으면 스케일 추정치다.
# 허수아비 목록: 이름에 '허수아비'가 든 엔티티를 별도 리스트로 표시
# (게임 좌표 + 모니터 위치, 캘리브레이션 기준점용. 움직이지 않으므로 회색 고정).
# 허수아비 캘리브레이션 모드: 허수아비 행 선택 → 게임에서 그 허수아비 위에 마우스 → F9.
# (게임 좌표 - self 게임 좌표, 마우스 모니터 좌표) 쌍을 scarecrow_calib.json에 저장하고
# 아핀을 계산해, 이후 모니터 위치를 스케일 추정치가 아닌 아핀으로 표시한다.
# (turnundead_mem의 calib.json과는 별개 파일이라, 그쪽 캘리브레이션은 건드리지 않는다.)
# F9는 keyboard 모듈의 전역 훅 (게임 창에 포커스가 있어도 동작). 없으면 pip install keyboard.

import json
import math
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import pyautogui as gu

try:
    import keyboard as kb
except Exception:
    kb = None

import memread as mr
from turnundead_mem import (
    CALIB_FILE,
    TARGET_NAMES,
    apply_affine,
    fit_affine,
    game_window_center,
    load_calib,
    raw_to_game,
)

POLL_INTERVAL = 0.1  # 초. 테이블 재읽기 간격.
MOVE_STICKY = 1.0  # 초. 움직인 뒤 굵은색을 유지하는 시간.
DEFAULT_SCALE = 8.0  # px/게임단위. 캘리브레이션 없을 때 몹 모니터 위치 추정치용.
CLICK_DIST_MAX = 10  # 게임 거리. 이 이하의 움직이는 몹만 휠클릭한다.
CLICK_COOLDOWN = 2.0  # 초. 휠클릭 간격 (스킬 쿨타임 고려, 한 번에 가장 가까운 1마리만).
SCARECROW_SUBSTR = '허수아비'  # 허수아비 목록: 이름에 이 문자열이 든 엔티티.
SC_CALIB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'scarecrow_calib.json')
SC_CALIB_HOTKEY = 'f9'  # 허수아비 캘리브레이션 포인트 추가 키 (turnundead_mem F9와 동일).


def load_sc_calib():
    try:
        with open(SC_CALIB_FILE, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        pts = [(float(p[0]), float(p[1]), float(p[2]), float(p[3]))
               for p in data.get('points', [])]
        return pts, fit_affine(pts)
    except Exception:
        return [], None


def save_sc_calib(points):
    with open(SC_CALIB_FILE, 'w', encoding='utf-8') as fh:
        json.dump({'points': [list(p) for p in points]}, fh)


class Poller(threading.Thread):
    """0.1초마다 테이블을 읽어 (self 모니터 위치, 근위병 리스트, 창 중심)을 큐에 넣는다."""

    def __init__(self, char_name, outq):
        super(Poller, self).__init__(daemon=True)
        self.char_name = char_name
        self.outq = outq
        self.stop_flag = threading.Event()
        self.mem = None
        self.err = None
        self.coef = None
        self.calib_mtime = None
        self.sc_coef = None
        self.sc_mean = None
        self.sc_loo = None
        self.sc_points = []
        self.sc_mtime = None
        self.latest = (None, [])
        self.latest_lock = threading.Lock()
        self.scale = DEFAULT_SCALE
        self.click_enabled = False  # GUI 휠클릭 체크박스로 켠다.
        self.last_click = 0.0
        self.prev_pos = {}  # id -> (gx, gy). 이동 판정용.
        self.last_move = {}  # id -> 마지막으로 위치가 바뀐 시각.

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

    def _reload_calib_if_changed(self):
        """calib.json이 바뀌었을 때만 다시 읽어 아핀 계수를 갱신한다."""
        try:
            mt = os.path.getmtime(CALIB_FILE)
        except Exception:
            mt = None
        if mt == self.calib_mtime:
            return
        self.calib_mtime = mt
        try:
            _pts, fit = load_calib()
            self.coef = fit[:6] if fit else None
        except Exception:
            self.coef = None

    def _reload_sc_calib_if_changed(self):
        """scarecrow_calib.json이 바뀌었을 때만 다시 읽어 아핀 계수를 갱신한다."""
        try:
            mt = os.path.getmtime(SC_CALIB_FILE)
        except Exception:
            mt = None
        if mt == self.sc_mtime:
            return
        self.sc_mtime = mt
        try:
            pts, fit = load_sc_calib()
            self.sc_points = pts
            if fit is not None:
                self.sc_coef = fit[:6]
                self.sc_mean = fit[6]
                self.sc_loo = fit[7]
            else:
                self.sc_coef = None
                self.sc_mean = None
                self.sc_loo = None
        except Exception:
            self.sc_coef = None
            self.sc_mean = None
            self.sc_loo = None

    def run(self):
        while not self.stop_flag.is_set():
            try:
                self._reload_calib_if_changed()
                self._reload_sc_calib_if_changed()
                objs, _head, _count = self.mem.entity_table()
                self_ent = None
                guards = []
                scarecrows = []
                for o in objs:
                    gx, gy = raw_to_game(o['x'], o['y'])
                    if o.get('name') == self.char_name and self_ent is None:
                        self_ent = {'id': o['id'], 'gx': gx, 'gy': gy}
                    if o.get('name') in TARGET_NAMES:
                        guards.append({'id': o['id'], 'gx': gx, 'gy': gy,
                                       'name': o.get('name')})
                    if o.get('name') and SCARECROW_SUBSTR in o.get('name'):
                        scarecrows.append({'id': o['id'], 'gx': gx, 'gy': gy,
                                           'name': o.get('name')})
                sw, sh = gu.size()
                mon_center = (sw // 2, sh // 2)
                wc = game_window_center()
                now = time.time()
                # 이동 판정 (id별 이전 위치와 비교, 1초간 굵은색 유지).
                cur_ids = set()
                for g in guards:
                    cur_ids.add(g['id'])
                    prev = self.prev_pos.get(g['id'])
                    if prev is not None and prev != (g['gx'], g['gy']):
                        self.last_move[g['id']] = now
                    g['moved'] = (g['id'] in self.last_move and
                                  now - self.last_move[g['id']] < MOVE_STICKY)
                self.prev_pos = {g['id']: (g['gx'], g['gy']) for g in guards}
                self.last_move = {i: t for i, t in self.last_move.items()
                                  if i in cur_ids}
                # 모니터 위치 우선순위: 허수아비 캘리브레이션 > calib.json > 스케일.
                use_coef = self.sc_coef if self.sc_coef is not None else self.coef
                self_mon = None
                self_mon_src = None
                if self_ent is not None:
                    for g in guards:
                        g['dist'] = math.hypot(g['gx'] - self_ent['gx'],
                                               g['gy'] - self_ent['gy'])
                    guards.sort(key=lambda g: g['dist'])
                    if use_coef is not None:
                        # 아핀 있음: 정확한 모니터 위치 (허수아비 캘리브레이션 우선).
                        fx, fy = apply_affine(use_coef, 0, 0)
                        self_mon = (int(round(fx)), int(round(fy)))
                        self_mon_src = ('허수아비 캘리브레이션'
                                        if self.sc_coef is not None else '캘리브레이션')
                        for g in guards:
                            mx, my = apply_affine(
                                use_coef,
                                g['gx'] - self_ent['gx'],
                                g['gy'] - self_ent['gy'])
                            g['mon'] = (int(round(mx)), int(round(my)))
                            g['estimated'] = False
                    else:
                        # 캘리브레이션 없음: self는 창 중심, 몹은 스케일 추정치.
                        if wc is not None:
                            self_mon = wc
                            self_mon_src = '창 중심'
                        else:
                            self_mon = mon_center
                            self_mon_src = '모니터 중심(폴백)'
                        cx, cy = self_mon
                        sc = self.scale
                        for g in guards:
                            mx = cx + (g['gx'] - self_ent['gx']) * sc
                            my = cy + (g['gy'] - self_ent['gy']) * sc
                            g['mon'] = (int(round(mx)), int(round(my)))
                            g['estimated'] = True
                else:
                    for g in guards:
                        g['mon'] = None
                        g['estimated'] = False
                # 허수아비: 게임 좌표 + 모니터 위치 (캘리브레이션 기준점용, 움직이지 않음).
                if self_ent is not None:
                    for sc in scarecrows:
                        sc['dist'] = math.hypot(sc['gx'] - self_ent['gx'],
                                                sc['gy'] - self_ent['gy'])
                    scarecrows.sort(key=lambda s: s['dist'])
                    if use_coef is not None:
                        for sc in scarecrows:
                            mx, my = apply_affine(
                                use_coef,
                                sc['gx'] - self_ent['gx'],
                                sc['gy'] - self_ent['gy'])
                            sc['mon'] = (int(round(mx)), int(round(my)))
                            sc['estimated'] = False
                    else:
                        cx, cy = self_mon
                        sc_scale = self.scale
                        for sc in scarecrows:
                            mx = cx + (sc['gx'] - self_ent['gx']) * sc_scale
                            my = cy + (sc['gy'] - self_ent['gy']) * sc_scale
                            sc['mon'] = (int(round(mx)), int(round(my)))
                            sc['estimated'] = True
                else:
                    for sc in scarecrows:
                        sc['mon'] = None
                        sc['estimated'] = False
                # 휠클릭: 켜져 있을 때만, 쿨타임마다 가장 가까운 대상 1마리.
                # 대상 = 움직이는 몹 + 게임 거리 10 이하 + 모니터 위치 있음. 가까운 순 정렬됨.
                clicked = None
                if (self.click_enabled and self_ent is not None and
                        now - self.last_click >= CLICK_COOLDOWN):
                    for g in guards:
                        if (g.get('moved') and g.get('dist', 999) <= CLICK_DIST_MAX
                                and g.get('mon') is not None):
                            try:
                                gu.moveTo(g['mon'][0], g['mon'][1])
                                gu.click(button='middle')
                                self.last_click = now
                                clicked = {'name': g['name'], 'id': g['id'],
                                           'mon': g['mon']}
                            except Exception:
                                pass
                            break
                with self.latest_lock:
                    self.latest = (self_ent, scarecrows)
                self.outq.put({
                    'self_id': self_ent['id'] if self_ent else None,
                    'self_mon': self_mon, 'self_mon_src': self_mon_src,
                    'guards': guards, 'win_center': wc,
                    'mon_center': mon_center,
                    'calib': self.coef is not None,
                    'sc_calib': {'n': len(self.sc_points),
                               'mean': self.sc_mean, 'loo': self.sc_loo,
                               'fitted': self.sc_coef is not None},
                    'scarecrows': scarecrows,
                    'clicked': clicked,
                    'time': time.strftime('%H:%M:%S')})
            except Exception as e:
                self.outq.put({'error': str(e)})
            self.stop_flag.wait(POLL_INTERVAL)

    def stop(self):
        self.stop_flag.set()
        if self.mem is not None:
            try:
                self.mem.detach()
            except Exception:
                pass
            self.mem = None


class App:
    def __init__(self, root):
        self.root = root
        root.title('내 캐릭터 위치 실시간 추적')
        self.q = queue.Queue()
        self.f9q = queue.Queue()
        self.poller = None
        self.sc_points, self.sc_fit = load_sc_calib()
        self.sc_hotkey_ok = False
        if kb is not None:
            try:
                kb.add_hotkey(SC_CALIB_HOTKEY, self._on_sc_hotkey)
                self.sc_hotkey_ok = True
            except Exception:
                pass
        self.font_bold = tkfont.Font(root, weight='bold')

        top = ttk.Frame(root, padding=10)
        top.pack(fill='x')
        ttk.Label(top, text='캐릭터:').pack(side='left')
        self.name_var = tk.StringVar(value='여포')
        ttk.Entry(top, textvariable=self.name_var, width=12).pack(side='left', padx=4)
        self.btn = ttk.Button(top, text='추적 시작', command=self.toggle)
        self.btn.pack(side='left', padx=4)

        # 스케일 조절 (캘리브레이션 없을 때만 사용).
        scale_row = ttk.Frame(root, padding=(10, 0))
        scale_row.pack(fill='x')
        ttk.Label(scale_row, text='스케일 (px/게임단위):').pack(side='left')
        self.scale_var = tk.StringVar(value=str(DEFAULT_SCALE))
        ttk.Entry(scale_row, textvariable=self.scale_var, width=8).pack(side='left', padx=4)
        ttk.Button(scale_row, text='적용', command=self.apply_scale).pack(side='left')
        ttk.Label(scale_row, text='(캘리브레이션 없을 때만 사용)').pack(side='left', padx=4)

        # 휠클릭 켜기 (기본 꺼짐. 켜면 움직이는 몹 + 거리 10 이하를 가까운 순으로 클릭).
        click_row = ttk.Frame(root, padding=(10, 0))
        click_row.pack(fill='x')
        self.click_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(click_row, text='휠클릭 켜기 (움직이는 몹, 거리 10 이하, 가까운 순)',
                        variable=self.click_var, command=self.on_click_toggle).pack(side='left')

        # 첫 줄: 내 캐릭터 모니터 위치 (실시간). 가장 크게.
        self.line1 = ttk.Label(root, text='추적 시작을 눌러주세요.',
                               font=('', 16, 'bold'), padding=(10, 12))
        self.line1.pack(fill='x')
        # 둘째 줄: sweep 중심 비교용 (게임 창 중심 vs 모니터 중심 + 캘리브레이션 여부).
        self.line2 = ttk.Label(root, text='', padding=(10, 2))
        self.line2.pack(fill='x')
        # 근위병 리스트 (모니터 위치, 가까운 순. 움직이면 굵은 검은색, 안 움직이면 회색).
        list_frame = ttk.Frame(root, padding=(10, 4))
        list_frame.pack(fill='both', expand=True)
        ttk.Label(list_frame, text='근위병 리스트 (가까운 순):').pack(anchor='w')
        # Listbox는 행별 font를 지원하지 않아 (itemconfig에 -font 없음) Treeview로 교체.
        # Treeview 태그는 행별 font/foreground를 지원한다.
        self.tree = ttk.Treeview(list_frame, columns=('info',), show='headings', height=10)
        self.tree.heading('info', text='이름 / id / 모니터 위치')
        self.tree.column('info', width=520)
        self.tree.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(list_frame, orient='vertical',
                           command=self.tree.yview)
        sb.pack(side='right', fill='y')
        self.tree.config(yscrollcommand=sb.set)
        self.tree.tag_configure('moving', font=self.font_bold, foreground='black')
        self.tree.tag_configure('still', foreground='gray')
        # 허수아비 목록 (게임 좌표 + 모니터 위치, 캘리브레이션 기준점용).
        sc_frame = ttk.Frame(root, padding=(10, 4))
        sc_frame.pack(fill='both', expand=True)
        ttk.Label(sc_frame, text='허수아비 목록 (게임 좌표 + 모니터 위치):').pack(anchor='w')
        self.sc_tree = ttk.Treeview(sc_frame, columns=('info',), show='headings', height=6)
        self.sc_tree.heading('info', text='이름 / id / 게임 좌표 / 모니터 위치')
        self.sc_tree.column('info', width=520)
        self.sc_tree.pack(side='left', fill='both', expand=True)
        sc_sb = ttk.Scrollbar(sc_frame, orient='vertical',
                              command=self.sc_tree.yview)
        sc_sb.pack(side='right', fill='y')
        self.sc_tree.config(yscrollcommand=sc_sb.set)
        self.sc_tree.tag_configure('still', foreground='gray')
        # 허수아비 캘리브레이션: 허수아비 행 선택 → 게임에서 그 허수아비 위에 마우스 → F9.
        cal_frame = ttk.Frame(root, padding=(10, 4))
        cal_frame.pack(fill='x')
        if self.sc_hotkey_ok:
            cal_txt = ('허수아비 캘리브레이션: 허수아비 행을 선택하고, 게임에서 그 허수아비 위에 '
                       '마우스를 올린 뒤 F9를 누른다. 서로 떨어진 허수아비 3개 이상. '
                       '캘리브레이션 중에는 캐릭터를 움직이지 말 것.')
        else:
            cal_txt = ('허수아비 캘리브레이션: keyboard 모듈이 없어 F9가 안 됨 '
                       '(pip install keyboard 후 재시작).')
        ttk.Label(cal_frame, text=cal_txt, wraplength=520, justify='left').pack(anchor='w')
        self.sc_cal_label = ttk.Label(cal_frame, text='', padding=(0, 2))
        self.sc_cal_label.pack(anchor='w')
        ttk.Button(cal_frame, text='허수아비 포인트 초기화',
                   command=self.on_clear_sc_calib).pack(anchor='w')
        # 마지막 휠클릭 표시.
        self.click_label = ttk.Label(root, text='', padding=(10, 2))
        self.click_label.pack(fill='x')
        # 상태 줄.
        self.status = ttk.Label(root, text='', padding=(10, 6))
        self.status.pack(fill='x')

        self.root.after(100, self.drain)
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    def _read_scale(self):
        try:
            v = float(self.scale_var.get())
            if v <= 0:
                return None
            return v
        except Exception:
            return None

    def apply_scale(self):
        v = self._read_scale()
        if v is None:
            self.status.config(text='스케일은 0보다 큰 숫자여야 해')
            return
        if self.poller is not None:
            self.poller.scale = v
        self.status.config(text='스케일 %.2f로 적용' % v)

    def on_click_toggle(self):
        if self.poller is not None:
            self.poller.click_enabled = self.click_var.get()
        if not self.click_var.get():
            self.click_label.config(text='휠클릭 꺼짐')

    def _on_sc_hotkey(self):
        # 키보드 훅 스레드에서 실행됨 — tkinter를 직접 건드리지 않고 큐로 넘긴다.
        self.f9q.put('__SC_CALIB__')

    def _refresh_sc_cal_label(self, n=None, mean=None, loo=None, fitted=None):
        if n is None:
            n = len(self.sc_points)
        if fitted is None:
            fitted = self.sc_fit is not None
        if fitted:
            txt = ('허수아비 캘리브레이션: 포인트 %d개, 평균오차 %.1fpx, LOO %.1fpx — 적용 중' % (
                n, mean if mean is not None else 0,
                loo if loo is not None else 0))
        elif n >= 3:
            txt = ('허수아비 캘리브레이션: 포인트 %d개 — fit 불안정 '
                   '(퍼짐 부족 또는 LOO 30px 초과, 서로 떨어진 허수아비로 다시 찍을 것)' % n)
        elif n > 0:
            txt = '허수아비 캘리브레이션: 포인트 %d개 (최소 3개 필요)' % n
        else:
            txt = '허수아비 캘리브레이션: 포인트 없음'
        self.sc_cal_label.config(text=txt)

    def on_sc_calib_point(self):
        sel = self.sc_tree.selection()
        if not sel:
            self.status.config(text='허수아비 캘리브레이션: 허수아비 행을 먼저 선택할 것')
            return
        try:
            sc_id = int(sel[0])
        except Exception:
            self.status.config(text='허수아비 캘리브레이션: 허수아비 행을 먼저 선택할 것')
            return
        if self.poller is None:
            self.status.config(text='허수아비 캘리브레이션: 추적 중일 때만 F9 가능')
            return
        with self.poller.latest_lock:
            self_ent, scs = self.poller.latest
        if self_ent is None:
            self.status.config(text='허수아비 캘리브레이션: self를 못 찾음')
            return
        tgt = None
        for sc in scs:
            if sc['id'] == sc_id:
                tgt = sc
                break
        if tgt is None:
            self.status.config(text='허수아비 캘리브레이션: 선택한 허수아비가 최신 스캔에 없음 (다시 선택)')
            return
        mx, my = gu.position()
        dx = tgt['gx'] - self_ent['gx']
        dy = tgt['gy'] - self_ent['gy']
        self.sc_points.append((float(dx), float(dy), float(mx), float(my)))
        self.sc_fit = fit_affine(self.sc_points)
        try:
            save_sc_calib(self.sc_points)
        except Exception as e:
            self.status.config(text='scarecrow_calib.json 저장 실패: %r' % (e,))
            return
        mean = self.sc_fit[6] if self.sc_fit else None
        loo = self.sc_fit[7] if self.sc_fit else None
        self._refresh_sc_cal_label(len(self.sc_points), mean, loo,
                                   self.sc_fit is not None)
        self.status.config(text='허수아비 포인트 추가: id %d (dx %d, dy %d -> 화면 %d,%d), 총 %d개' % (
            sc_id, dx, dy, mx, my, len(self.sc_points)))
        if self.sc_fit is None and len(self.sc_points) >= 3:
            self.status.config(text=self.status.cget('text') +
                               ' — fit 불안정 (퍼지게 다시 찍을 것)')

    def on_clear_sc_calib(self):
        self.sc_points = []
        self.sc_fit = None
        try:
            if os.path.isfile(SC_CALIB_FILE):
                os.remove(SC_CALIB_FILE)
        except Exception:
            pass
        self._refresh_sc_cal_label(0, None, None, False)
        self.status.config(text='허수아비 포인트 초기화됨')

    def toggle(self):
        if self.poller is not None:
            self.poller.stop()
            self.poller = None
            self.btn.config(text='추적 시작')
            self.status.config(text='중지됨')
            return
        p = Poller(self.name_var.get().strip() or '여포', self.q)
        v = self._read_scale()
        if v is not None:
            p.scale = v
        if not p.attach():
            self.status.config(text=p.err)
            return
        self.poller = p
        p.click_enabled = self.click_var.get()
        while not self.f9q.empty():
            try:
                self.f9q.get_nowait()
            except queue.Empty:
                break
        p.start()
        self.btn.config(text='중지')
        self.status.config(text='추적 중 (0.1초마다 갱신)')

    def drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                self.show(item)
        except queue.Empty:
            pass
        try:
            while True:
                sig = self.f9q.get_nowait()
                if sig == '__SC_CALIB__':
                    self.on_sc_calib_point()
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def show(self, item):
        if 'error' in item:
            self.status.config(text='오류: ' + item['error'])
            return
        clicked = item.get('clicked')
        if clicked:
            self.click_label.config(
                text='휠클릭: %s id %d 모니터 (%d, %d) %s' % (
                    clicked['name'], clicked['id'],
                    clicked['mon'][0], clicked['mon'][1], item['time']))
        name = self.name_var.get().strip() or '여포'
        if item['self_mon'] is None:
            self.line1.config(text='%s를 못 찾음 (게임 실행 중? 이름 확인)' % name)
        else:
            self.line1.config(
                text='%s (id %s): 모니터 (%d, %d)  [%s]  %s' % (
                    name, item['self_id'], item['self_mon'][0],
                    item['self_mon'][1], item['self_mon_src'], item['time']))
        wc = item['win_center']
        mc = item['mon_center']
        sc_cal0 = item.get('sc_calib')
        if sc_cal0 is not None and sc_cal0.get('fitted'):
            calib_txt = '허수아비 캘리브레이션 적용 중'
        elif item['calib']:
            calib_txt = '캘리브레이션 있음'
        else:
            calib_txt = '캘리브레이션 없음'
        if wc is None:
            self.line2.config(text='게임 창 중심: 못 찾음 (모니터 중심 %d,%d)  |  %s' % (
                mc[0], mc[1], calib_txt))
        else:
            self.line2.config(text='게임 창 중심: %d,%d  |  모니터 중심: %d,%d  |  %s' % (
                wc[0], wc[1], mc[0], mc[1], calib_txt))
        for row in self.tree.get_children():
            self.tree.delete(row)
        guards = item['guards']
        if not guards:
            self.tree.insert('', 'end', values=('근위병 없음',), tags=('still',))
        elif item['self_mon'] is None:
            for g in guards:
                self.tree.insert('', 'end',
                                values=('%s id %d (self 없음)' % (g['name'], g['id']),),
                                tags=('still',))
        else:
            for i, g in enumerate(guards, 1):
                if g.get('estimated'):
                    txt = '#%d %s id %d: 모니터 (%d, %d) (추정)' % (
                        i, g['name'], g['id'], g['mon'][0], g['mon'][1])
                else:
                    txt = '#%d %s id %d: 모니터 (%d, %d)' % (
                        i, g['name'], g['id'], g['mon'][0], g['mon'][1])
                tag = 'moving' if g.get('moved') else 'still'
                self.tree.insert('', 'end', values=(txt,), tags=(tag,))
        # 새로고침(0.1초마다 전부 지우고 다시 그림)으로 선택이 날아가는 문제 방지:
        # 지우기 전에 선택한 허수아비 id를 기억해뒀다가, 다시 그린 뒤 같은 id를 재선택한다.
        sc_sel = self.sc_tree.selection()
        sc_sel_id = sc_sel[0] if sc_sel else None
        for row in self.sc_tree.get_children():
            self.sc_tree.delete(row)
        scs = item.get('scarecrows', [])
        if not scs:
            self.sc_tree.insert('', 'end',
                                values=('허수아비 없음 (이름에 "허수아비"가 든 엔티티가 없음)',),
                                tags=('still',))
        elif item['self_mon'] is None:
            for sc in scs:
                self.sc_tree.insert('', 'end',
                                    values=('%s id %d: 게임 (%d, %d) (self 없음)' % (
                                        sc['name'], sc['id'], sc['gx'], sc['gy']),),
                                    tags=('still',), iid=str(sc['id']))
        else:
            for i, sc in enumerate(scs, 1):
                if sc.get('estimated'):
                    txt = '#%d %s id %d: 게임 (%d, %d) 모니터 (%d, %d) (추정)' % (
                        i, sc['name'], sc['id'], sc['gx'], sc['gy'],
                        sc['mon'][0], sc['mon'][1])
                else:
                    txt = '#%d %s id %d: 게임 (%d, %d) 모니터 (%d, %d)' % (
                        i, sc['name'], sc['id'], sc['gx'], sc['gy'],
                        sc['mon'][0], sc['mon'][1])
                self.sc_tree.insert('', 'end', values=(txt,), tags=('still',),
                                    iid=str(sc['id']))
        sc_cal = item.get('sc_calib')
        if sc_cal is not None:
            self._refresh_sc_cal_label(sc_cal['n'], sc_cal.get('mean'),
                                       sc_cal.get('loo'), sc_cal.get('fitted'))
        if sc_sel_id is not None:
            try:
                if self.sc_tree.exists(sc_sel_id):
                    self.sc_tree.selection_set(sc_sel_id)
                    self.sc_tree.focus(sc_sel_id)
            except Exception:
                pass

    def on_close(self):
        if self.poller is not None:
            self.poller.stop()
            self.poller = None
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
