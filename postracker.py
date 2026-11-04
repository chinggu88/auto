# postracker.py — 내 캐릭터 위치 실시간 추적 GUI (진단용)
# 사용법: repo 폴더에서 python postracker.py
#   (memread.py + mem.json + turnundead_mem.py가 같은 폴더에 있어야 함)
# 첫 줄: 내 캐릭터(기본 여포)의 모니터 위치를 실시간으로 표시한다 (게임 좌표 아님).
#   (sweep 중심/방향이 맞는지 눈으로 확인하는 용도. 클릭은 안 한다.)
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

import math
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import pyautogui as gu

import memread as mr
from turnundead_mem import (
    CALIB_FILE,
    TARGET_NAMES,
    apply_affine,
    game_window_center,
    load_calib,
    raw_to_game,
)

POLL_INTERVAL = 0.1  # 초. 테이블 재읽기 간격.
MOVE_STICKY = 1.0  # 초. 움직인 뒤 굵은색을 유지하는 시간.
DEFAULT_SCALE = 8.0  # px/게임단위. 캘리브레이션 없을 때 몹 모니터 위치 추정치용.
CLICK_DIST_MAX = 10  # 게임 거리. 이 이하의 움직이는 몹만 휠클릭한다.
CLICK_COOLDOWN = 2.0  # 초. 휠클릭 간격 (스킬 쿨타임 고려, 한 번에 가장 가까운 1마리만).


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

    def run(self):
        while not self.stop_flag.is_set():
            try:
                self._reload_calib_if_changed()
                objs, _head, _count = self.mem.entity_table()
                self_ent = None
                guards = []
                for o in objs:
                    gx, gy = raw_to_game(o['x'], o['y'])
                    if o.get('name') == self.char_name and self_ent is None:
                        self_ent = {'id': o['id'], 'gx': gx, 'gy': gy}
                    if o.get('name') in TARGET_NAMES:
                        guards.append({'id': o['id'], 'gx': gx, 'gy': gy,
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
                self_mon = None
                self_mon_src = None
                if self_ent is not None:
                    for g in guards:
                        g['dist'] = math.hypot(g['gx'] - self_ent['gx'],
                                               g['gy'] - self_ent['gy'])
                    guards.sort(key=lambda g: g['dist'])
                    if self.coef is not None:
                        # 캘리브레이션 있음: 아핀으로 정확한 모니터 위치.
                        fx, fy = apply_affine(self.coef, 0, 0)
                        self_mon = (int(round(fx)), int(round(fy)))
                        self_mon_src = '캘리브레이션'
                        for g in guards:
                            mx, my = apply_affine(
                                self.coef,
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
                self.outq.put({
                    'self_id': self_ent['id'] if self_ent else None,
                    'self_mon': self_mon, 'self_mon_src': self_mon_src,
                    'guards': guards, 'win_center': wc,
                    'mon_center': mon_center,
                    'calib': self.coef is not None,
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
        self.poller = None
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
        calib_txt = '캘리브레이션 있음' if item['calib'] else '캘리브레이션 없음'
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

    def on_close(self):
        if self.poller is not None:
            self.poller.stop()
            self.poller = None
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
