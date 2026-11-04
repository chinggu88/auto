# postracker.py — 내 캐릭터 위치 실시간 추적 GUI (진단용)
# 사용법: repo 폴더에서 python postracker.py (memread.py + mem.json이 같은 폴더에 있어야 함)
# 첫 줄: 내 캐릭터(기본 여포)의 게임 좌표를 실시간으로 표시한다.
#   (sweep 중심/방향이 맞는지 눈으로 확인하는 용도. 클릭은 안 한다.)
# 아래 줄: 게임 창 중심 + 모니터 중심 (sweep 중심 비교용), 가장 가까운 근위병.
# 폴링: 백그라운드 스레드가 0.5초마다 테이블을 읽고, GUI는 큐로 받아 표시한다.

import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import pyautogui as gu

import memread as mr

TARGET_NAMES = [
    '야히의 근위병(데몬)',
    '야히의 근위병(베레스)',
    '야히의 근위병(서큐버스)',
]
POLL_INTERVAL = 0.5  # 초. 테이블 재읽기 간격.


def raw_to_game(rx, ry):
    """엔티티 테이블 raw 좌표 -> 게임 좌표. x는 (raw+32768)/2, y는 raw 그대로."""
    return ((rx & 0xFFFF) + 32768) // 2, ry


def game_window_center():
    """Lineage 게임 창의 중심 좌표 (x, y). 못 찾으면 None."""
    try:
        wins = gu.getWindowsWithTitle('Lineage')
    except Exception:
        return None
    if not wins:
        return None
    for w in wins:
        try:
            if w.title == 'Lineage Windows Client':
                return (w.left + w.width // 2, w.top + w.height // 2)
        except Exception:
            continue
    try:
        w = wins[0]
        return (w.left + w.width // 2, w.top + w.height // 2)
    except Exception:
        return None


class Poller(threading.Thread):
    """0.5초마다 테이블을 읽어 (self, 근위병, 창 중심)을 큐에 넣는다."""

    def __init__(self, char_name, outq):
        super(Poller, self).__init__(daemon=True)
        self.char_name = char_name
        self.outq = outq
        self.stop_flag = threading.Event()
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

    def run(self):
        while not self.stop_flag.is_set():
            try:
                objs, _head, _count = self.mem.entity_table()
                self_ent = None
                guards = []
                for o in objs:
                    gx, gy = raw_to_game(o['x'], o['y'])
                    if o.get('name') == self.char_name and self_ent is None:
                        self_ent = {'id': o['id'], 'gx': gx, 'gy': gy,
                                    'rx': o['x'], 'ry': o['y'], 'name': o.get('name')}
                    if o.get('name') in TARGET_NAMES:
                        guards.append({'id': o['id'], 'gx': gx, 'gy': gy,
                                       'name': o.get('name')})
                if self_ent is not None:
                    for g in guards:
                        g['dist'] = math.hypot(g['gx'] - self_ent['gx'],
                                               g['gy'] - self_ent['gy'])
                    guards.sort(key=lambda g: g['dist'])
                sw, sh = gu.size()
                wc = game_window_center()
                self.outq.put({'self': self_ent, 'guards': guards,
                               'win_center': wc, 'mon_center': (sw // 2, sh // 2),
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

        # 첫 줄: 내 캐릭터 위치 (실시간). 가장 크게.
        self.line1 = ttk.Label(root, text='추적 시작을 눌러주세요.',
                               font=('', 16, 'bold'), padding=(10, 12))
        self.line1.pack(fill='x')
        # 둘째 줄: sweep 중심 비교용 (게임 창 중심 vs 모니터 중심).
        self.line2 = ttk.Label(root, text='', padding=(10, 2))
        self.line2.pack(fill='x')
        # 셋째 줄: 가장 가까운 근위병.
        self.line3 = ttk.Label(root, text='', padding=(10, 2))
        self.line3.pack(fill='x')
        # 상태 줄.
        self.status = ttk.Label(root, text='', padding=(10, 6))
        self.status.pack(fill='x')

        self.root.after(200, self.drain)
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
        self.status.config(text='추적 중 (0.5초마다 갱신)')

    def drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                self.show(item)
        except queue.Empty:
            pass
        self.root.after(200, self.drain)

    def show(self, item):
        if 'error' in item:
            self.status.config(text='오류: ' + item['error'])
            return
        name = self.name_var.get().strip() or '여포'
        self_ent = item['self']
        if self_ent is None:
            self.line1.config(text='%s를 못 찾음 (게임 실행 중? 이름 확인)' % name)
            self.line3.config(text='')
        else:
            self.line1.config(
                text='%s (id %d): 게임 (%d, %d)  [raw %d, %d]  %s' % (
                    name, self_ent['id'], self_ent['gx'], self_ent['gy'],
                    self_ent['rx'], self_ent['ry'], item['time']))
            guards = item['guards']
            if guards:
                g = guards[0]
                self.line3.config(
                    text='가장 가까운 근위병: %s id %d (게임 %d,%d) 거리 %.0f (총 %d마리)' % (
                        g['name'], g['id'], g['gx'], g['gy'], g['dist'], len(guards)))
            else:
                self.line3.config(text='근위병 없음')
        wc = item['win_center']
        mc = item['mon_center']
        if wc is None:
            self.line2.config(text='게임 창 중심: 못 찾음 (모니터 중심 %d,%d로 폴백)' % mc)
        else:
            self.line2.config(text='게임 창 중심: %d,%d  |  모니터 중심: %d,%d' % (
                wc[0], wc[1], mc[0], mc[1]))

    def on_close(self):
        if self.poller is not None:
            self.poller.stop()
            self.poller = None
        self.root.destroy()


if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()
