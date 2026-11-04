# postracker.py — 내 캐릭터 위치 실시간 추적 GUI (진단용)
# 사용법: repo 폴더에서 python postracker.py
#   (memread.py + mem.json + turnundead_mem.py가 같은 폴더에 있어야 함)
# 첫 줄: 내 캐릭터(기본 여포)의 모니터 위치를 실시간으로 표시한다 (게임 좌표 아님).
#   (sweep 중심/방향이 맞는지 눈으로 확인하는 용도. 클릭은 안 한다.)
# 아래: 게임 창 중심 vs 모니터 중심, 근위병 리스트 (모니터 위치, 가까운 순).
# 모니터 위치 계산:
#   - calib.json이 있으면 turnundead_mem의 캘리브레이션(아핀)으로 게임 좌표 -> 화면 좌표 변환.
#     (아핀은 상대 게임 좌표(몹-self) -> 절대 화면 좌표. self 화면 위치 = 아핀(0,0).)
#   - calib.json이 없으면 정확한 몹 화면 px는 스케일을 몰라 계산 불가.
#     self는 게임 창 중심(가정), 몹은 중심에서 방향(단위벡터)만 표시한다.
#     F9 캘리브레이션(turnundead_mem)을 한 번 하면 정확한 모니터 위치가 나온다.
# 폴링: 백그라운드 스레드가 0.1초마다 테이블을 읽고, GUI는 큐로 받아 표시한다.

import math
import os
import queue
import threading
import time
import tkinter as tk
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
                self_mon = None
                self_mon_src = None
                if self_ent is not None:
                    for g in guards:
                        g['dist'] = math.hypot(g['gx'] - self_ent['gx'],
                                               g['gy'] - self_ent['gy'])
                    guards.sort(key=lambda g: g['dist'])
                    if self.coef is not None:
                        # 캘리브레이션 있음: 아핀으로 모니터 위치 계산.
                        fx, fy = apply_affine(self.coef, 0, 0)
                        self_mon = (int(round(fx)), int(round(fy)))
                        self_mon_src = '캘리브레이션'
                        for g in guards:
                            mx, my = apply_affine(
                                self.coef,
                                g['gx'] - self_ent['gx'],
                                g['gy'] - self_ent['gy'])
                            g['mon'] = (int(round(mx)), int(round(my)))
                            g['dir'] = None
                    else:
                        # 캘리브레이션 없음: self는 창 중심(가정), 몹은 방향만.
                        if wc is not None:
                            self_mon = wc
                            self_mon_src = '창 중심'
                        else:
                            self_mon = mon_center
                            self_mon_src = '모니터 중심(폴백)'
                        for g in guards:
                            dx = g['gx'] - self_ent['gx']
                            dy = g['gy'] - self_ent['gy']
                            dist = math.hypot(dx, dy)
                            if dist < 1e-9:
                                g['dir'] = (0.0, 0.0)
                            else:
                                g['dir'] = (dx / dist, dy / dist)
                            g['mon'] = None
                else:
                    for g in guards:
                        g['mon'] = None
                        g['dir'] = None
                self.outq.put({
                    'self_id': self_ent['id'] if self_ent else None,
                    'self_mon': self_mon, 'self_mon_src': self_mon_src,
                    'guards': guards, 'win_center': wc,
                    'mon_center': mon_center,
                    'calib': self.coef is not None,
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

        top = ttk.Frame(root, padding=10)
        top.pack(fill='x')
        ttk.Label(top, text='캐릭터:').pack(side='left')
        self.name_var = tk.StringVar(value='여포')
        ttk.Entry(top, textvariable=self.name_var, width=12).pack(side='left', padx=4)
        self.btn = ttk.Button(top, text='추적 시작', command=self.toggle)
        self.btn.pack(side='left', padx=4)

        # 첫 줄: 내 캐릭터 모니터 위치 (실시간). 가장 크게.
        self.line1 = ttk.Label(root, text='추적 시작을 눌러주세요.',
                               font=('', 16, 'bold'), padding=(10, 12))
        self.line1.pack(fill='x')
        # 둘째 줄: sweep 중심 비교용 (게임 창 중심 vs 모니터 중심 + 캘리브레이션 여부).
        self.line2 = ttk.Label(root, text='', padding=(10, 2))
        self.line2.pack(fill='x')
        # 근위병 리스트 (모니터 위치, 가까운 순).
        list_frame = ttk.Frame(root, padding=(10, 4))
        list_frame.pack(fill='both', expand=True)
        ttk.Label(list_frame, text='근위병 리스트 (가까운 순):').pack(anchor='w')
        self.listbox = tk.Listbox(list_frame, height=10)
        self.listbox.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(list_frame, orient='vertical',
                           command=self.listbox.yview)
        sb.pack(side='right', fill='y')
        self.listbox.config(yscrollcommand=sb.set)
        # 상태 줄.
        self.status = ttk.Label(root, text='', padding=(10, 6))
        self.status.pack(fill='x')

        self.root.after(100, self.drain)
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    def toggle(self):
        if self.poller is not None:
            self.poller.stop()
            self.poller = None
            self.btn.config(text='추적 시작')
            self.status.config(text='중지됨')
            return
        p = Poller(self.name_var.get().strip() or '여포', self.q)
        if not p.attach():
            self.status.config(text=p.err)
            return
        self.poller = p
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
        self.listbox.delete(0, 'end')
        guards = item['guards']
        if not guards:
            self.listbox.insert('end', '근위병 없음')
        elif item['self_mon'] is None:
            for g in guards:
                self.listbox.insert('end', '%s id %d (self 없음)' % (g['name'], g['id']))
        elif item['calib']:
            for i, g in enumerate(guards, 1):
                self.listbox.insert(
                    'end', '#%d %s id %d: 모니터 (%d, %d)' % (
                        i, g['name'], g['id'], g['mon'][0], g['mon'][1]))
        else:
            for i, g in enumerate(guards, 1):
                self.listbox.insert(
                    'end', '#%d %s id %d: 방향 (%.2f, %.2f)' % (
                        i, g['name'], g['id'], g['dir'][0], g['dir'][1]))

    def on_close(self):
        if self.poller is not None:
            self.poller.stop()
            self.poller = None
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
