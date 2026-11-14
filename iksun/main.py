#iksun/main.py - 자동사냥 설정 프로그램 시작 파일
#
#  창 하나에 탭 4개(내정보 / 버프 / 사냥 / 쫄)를 띄우고, 시작하면 작업 스레드 하나가
#  0.2초마다 아래 순서로 돈다 (기획서 '자동사냥 설정 프로그램 기획서' 기준):
#    1. 메모리에서 캐릭터 정보를 읽는다 (못 읽으면 멈춘다)
#    2. 버프 탭의 생존 트리거 -> 걸리면 그 키를 누르고, 정지 트리거면 여기서 멈춘다
#    3. 버프 탭의 버프 주기
#    4. 내정보에서 고른 모드 하나 (사냥 또는 쫄)
#
#  이미지 감지는 쓰지 않는다. 메모리만 읽고(memread.py), 마법 대상 id 한 칸만 쓴다(memcast.py).
#  memread.py / memcast.py / mem.json 은 상위 폴더(저장소 루트)의 것을 그대로 쓴다.
#
#  실행 : python iksun/main.py   (Windows, 게임과 같은 관리자 권한으로)

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import memread as mr

import tab_myinfo
import tab_buff
import tab_hunt
import tab_support

SETTINGS_PATH = os.path.join(HERE, 'settings.json')
TOKENS_PATH   = os.path.join(HERE, 'design-system', 'tokens.json')
MEM_PATH      = os.path.join(ROOT, 'mem.json')
LOG_DIR       = os.path.join(HERE, 'logs')

TICK = 0.2          #작업 스레드 한 바퀴 간격(초)

#tokens.json 을 못 읽을 때 쓰는 어두운 테마 기본값 (값은 tokens.json 과 같다)
DEFAULT_COLORS = {
    'bg': '#121417', 'surface': '#1b1e23', 'surface-raised': '#262a31',
    'line': '#323741', 'line-strong': '#6b7380',
    'ink': '#e8eaed', 'ink-muted': '#9aa1ab',
    'accent': '#4c9aff', 'accent-ink': '#0b0d10',
    'state-ok': '#5ab4ff', 'state-unknown': '#f5a524',
    'state-danger': '#ff6b6b', 'state-idle': '#8b929c',
}


#디자인 시스템(tokens.json)의 어두운 테마 색을 읽는다
def loadcolors():
    colors = dict(DEFAULT_COLORS)
    try:
        f = open(TOKENS_PATH, 'r', encoding='utf-8')
        data = json.load(f)
        f.close()
        for t in data['color']['tokens']:
            v = t.get('value') or {}
            if 'dark' in v:
                colors[t['name']] = v['dark']
    except Exception:
        pass
    return colors


#탭들이 같이 쓰는 상태. 작업 스레드와 화면 스레드가 함께 본다
class Ctx(object):
    def __init__(self):
        self.mem     = None         #붙어 있는 mr.Mem (없으면 None)
        self.caster  = None         #memcast.Caster (마법 시전이 필요할 때 만든다)
        self.info    = None         #마지막으로 읽은 charinfo dict
        self.mode    = 'hunt'       #'hunt' 또는 'support'
        self.running = False
        self.stopreq = threading.Event()
        self.logq    = queue.Queue()
        self.started = 0.0          #시작 시각 (사냥 시간 제한에 쓴다)

    #종류 : '정보' / '행동' / '트리거' / '오류'
    def log(self, kind, text):
        self.logq.put((time.strftime('%H:%M:%S'), kind, text))

    #게임 창이 맨 앞일 때만 키를 누른다 (다른 창에 키가 들어가는 것을 막는다)
    def press(self, key, why=''):
        if self.mem == None or self.mem.pid == None:
            return False
        try:
            if mr.frontpid() != self.mem.pid:
                self.log('정보', '게임 창이 맨 앞이 아니라 %s 를 안 누름' % key)
                return False
            import pyautogui
            pyautogui.press(key.lower())
        except Exception as e:
            self.log('오류', '%s 누르기 실패 : %s' % (key, e))
            return False
        self.log('행동', '%s 누름%s' % (key.upper(), (' (' + why + ')') if why else ''))
        return True

    #마법 시전 (대상 id 를 메모리에 쓰고 그 마법이 든 단축키를 누른다)
    def cast(self, target, spell):
        if self.mem == None:
            return None
        if self.caster == None:
            import memcast
            self.caster = memcast.Caster(self.mem)
        r = self.caster.cast(target['id'], target.get('ptr'), spell)
        kind = '행동' if r.get('state') == 'sent' else '정보'
        self.log(kind, '%s -> %s : %s' % (spell, target.get('name') or target['id'], r.get('msg')))
        return r

    def requeststop(self, why):
        if self.running:
            self.log('트리거', '정지 : ' + why)
        self.stopreq.set()


class App(object):
    def __init__(self, root):
        self.root   = root
        self.mempath = MEM_PATH
        self.ctx    = Ctx()
        self.colors = loadcolors()
        self.worker = None
        self.logfile = None

        root.title('Lin Auto 제어판')
        root.geometry('760x720')
        root.minsize(560, 520)
        self.style()

        #탭 위의 한 줄 상태 표시줄 : 연결 / 모드 / HP / MP
        bar = ttk.Frame(root, style='Bar.TFrame', padding=(12, 8))
        bar.pack(fill='x')
        self.st_conn = ttk.Label(bar, text='미연결', style='Idle.Bar.TLabel')
        self.st_conn.pack(side='left')
        self.st_mode = ttk.Label(bar, text='', style='Bar.TLabel')
        self.st_mode.pack(side='left', padx=(16, 0))
        self.st_hpmp = ttk.Label(bar, text='HP -  MP -', style='Mono.Bar.TLabel')
        self.st_hpmp.pack(side='right')

        nb = ttk.Notebook(root)
        nb.pack(fill='both', expand=True, padx=8, pady=8)
        self.myinfo  = tab_myinfo.MyInfoTab(nb, self)
        self.buff    = tab_buff.BuffTab(nb, self)
        self.hunt    = tab_hunt.HuntTab(nb, self)
        self.support = tab_support.SupportTab(nb, self)
        nb.add(self.myinfo,  text='내정보')
        nb.add(self.buff,    text='버프')
        nb.add(self.hunt,    text='사냥')
        nb.add(self.support, text='쫄')

        self.tabs = {'myinfo': self.myinfo, 'buff': self.buff,
                     'hunt': self.hunt, 'support': self.support}
        self.loadsettings()

        #어느 탭에서든 Tab 키로 정지 (keyboard 가 없으면 버튼으로만 정지)
        try:
            import keyboard
            keyboard.add_hotkey('tab', lambda: self.ctx.requeststop('Tab 키'))
        except Exception:
            self.ctx.log('정보', 'keyboard 모듈이 없어 Tab 정지 단축키를 못 걸었다 - 정지 버튼을 쓴다')

        root.protocol('WM_DELETE_WINDOW', self.onclose)
        self.poll()

    #--- 화면 ---

    def style(self):
        c = self.colors
        self.root.configure(bg=c['bg'])
        s = ttk.Style(self.root)
        try:
            s.theme_use('clam')
        except Exception:
            pass
        sans = ('Malgun Gothic', 10)
        s.configure('.', background=c['surface'], foreground=c['ink'], font=sans,
                    fieldbackground=c['surface-raised'], bordercolor=c['line-strong'])
        s.configure('TFrame', background=c['surface'])
        s.configure('TLabel', background=c['surface'], foreground=c['ink'])
        s.configure('Muted.TLabel', foreground=c['ink-muted'])
        s.configure('Mono.TLabel', font=('Consolas', 10))
        s.configure('Readout.TLabel', font=('Consolas', 16, 'bold'))
        s.configure('TLabelframe', background=c['surface'], bordercolor=c['line'])
        s.configure('TLabelframe.Label', background=c['surface'], foreground=c['ink'],
                    font=('Malgun Gothic', 10, 'bold'))
        s.configure('TCheckbutton', background=c['surface'], foreground=c['ink'])
        s.configure('TRadiobutton', background=c['surface'], foreground=c['ink'])
        s.configure('TEntry', fieldbackground=c['surface-raised'], foreground=c['ink'])
        s.configure('TCombobox', fieldbackground=c['surface-raised'], foreground=c['ink'])
        s.configure('TNotebook', background=c['bg'], bordercolor=c['line'])
        s.configure('TNotebook.Tab', background=c['surface-raised'], foreground=c['ink-muted'],
                    padding=(14, 6))
        s.map('TNotebook.Tab', background=[('selected', c['surface'])],
              foreground=[('selected', c['ink'])])
        s.configure('TButton', background=c['surface-raised'], foreground=c['ink'], padding=(10, 4))
        s.configure('Accent.TButton', background=c['accent'], foreground=c['accent-ink'],
                    font=('Malgun Gothic', 10, 'bold'))
        s.configure('Bar.TFrame', background=c['bg'])
        s.configure('Bar.TLabel', background=c['bg'], foreground=c['ink'])
        s.configure('Mono.Bar.TLabel', background=c['bg'], foreground=c['ink'], font=('Consolas', 10, 'bold'))
        for name, key in (('Ok', 'state-ok'), ('Idle', 'state-idle'),
                          ('Unknown', 'state-unknown'), ('Danger', 'state-danger')):
            s.configure(name + '.Bar.TLabel', background=c['bg'], foreground=c[key],
                        font=('Malgun Gothic', 10, 'bold'))
            s.configure(name + '.TLabel', foreground=c[key], font=('Malgun Gothic', 10, 'bold'))

    #화면 스레드에서 0.2초마다 : 로그를 옮기고 상태 표시줄을 갱신한다
    def poll(self):
        try:
            while True:
                t, kind, text = self.ctx.logq.get_nowait()
                self.myinfo.addlog(t, kind, text)
                self.writelog(t, kind, text)
        except queue.Empty:
            pass

        ctx = self.ctx
        if ctx.mem != None and ctx.mem.attached():
            if ctx.mem.stale:
                self.st_conn.configure(text='판단불가 · 메모리 stale', style='Unknown.Bar.TLabel')
            else:
                self.st_conn.configure(text='연결됨 · PID %d' % ctx.mem.pid, style='Ok.Bar.TLabel')
        else:
            self.st_conn.configure(text='미연결', style='Idle.Bar.TLabel')
        mode = '사냥' if ctx.mode == 'hunt' else '쫄'
        self.st_mode.configure(text=('%s 실행 중' % mode) if ctx.running else ('모드 : ' + mode))
        i = ctx.info
        if i != None:
            self.st_hpmp.configure(text='HP %s/%s  MP %s/%s' % (i.get('hp'), i.get('hp_max'),
                                                                 i.get('mp'), i.get('mp_max')))
        if self.worker != None and not self.worker.is_alive():
            self.worker = None
            ctx.running = False
            self.myinfo.setrunning(False)
        self.root.after(200, self.poll)

    #로그 파일 : logs/YYYY-MM-DD.txt
    def writelog(self, t, kind, text):
        try:
            if not os.path.isdir(LOG_DIR):
                os.makedirs(LOG_DIR)
            path = os.path.join(LOG_DIR, time.strftime('%Y-%m-%d') + '.txt')
            f = open(path, 'a', encoding='utf-8')
            f.write('%s  %s  %s\n' % (t, kind, text))
            f.close()
        except Exception:
            pass

    #--- 연결 ---

    def connect(self, pid=None):
        self.disconnect()
        m = mr.Mem(MEM_PATH, lambda s: self.ctx.log('정보', s))
        try:
            ok = m.attach(pid)
        except Exception as e:
            self.ctx.log('오류', '연결 실패 : %s' % e)
            return False
        if not ok:
            self.ctx.log('오류', '연결 실패 : %s' % m.err)
            return False
        self.ctx.mem = m
        return True

    def disconnect(self):
        if self.ctx.running:
            self.ctx.requeststop('연결 해제')
        if self.ctx.caster != None:
            self.ctx.caster.close()
            self.ctx.caster = None
        if self.ctx.mem != None:
            self.ctx.mem.detach()
            self.ctx.mem = None
        self.ctx.info = None

    #--- 실행 ---

    #시작 전 점검. 막히면 이유 문자열, 괜찮으면 None
    def precheck(self):
        ctx = self.ctx
        if ctx.mem == None or not ctx.mem.attached():
            return '게임에 연결되지 않았다'
        for name in ('buff', ctx.mode):
            why = self.tabs[name].precheck(ctx)
            if why:
                return why
        return None

    def start(self):
        if self.ctx.running:
            return
        why = self.precheck()
        if why:
            self.ctx.log('오류', '시작 못 함 : ' + why)
            return
        self.savesettings()
        ctx = self.ctx
        ctx.stopreq.clear()
        ctx.running = True
        ctx.started = time.time()
        self.buff.begin(ctx)
        self.tabs[ctx.mode].begin(ctx)
        self.myinfo.setrunning(True)
        ctx.log('정보', '시작 : ' + ('사냥' if ctx.mode == 'hunt' else '쫄') + ' 모드')
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def stop(self):
        self.ctx.requeststop('정지 버튼')

    #작업 스레드
    def run(self):
        ctx = self.ctx
        try:
            while not ctx.stopreq.is_set():
                t0 = time.time()
                info = ctx.mem.charinfo() if ctx.mem != None else None
                if info == None or info.get('hp') == None or info.get('hp_max') in (None, 0):
                    ctx.requeststop('HP 를 못 읽음 (판단불가)')
                    break
                ctx.info = info
                #생존 트리거가 먼저. 'stop' 이면 멈추고, 'acted' 면 이번 바퀴는 다른 동작을 안 한다
                r = self.buff.survive(ctx, info)
                if r == 'stop':
                    break
                if r != 'acted' and not self.buff.dobuffs(ctx):
                    self.tabs[ctx.mode].tick(ctx, info)
                time.sleep(max(0.0, TICK - (time.time() - t0)))
        except Exception as e:
            ctx.log('오류', '작업 스레드 오류 : %s' % e)
        finally:
            ctx.running = False
            ctx.log('정보', '정지됨')

    #--- 설정 ---

    def loadsettings(self):
        data = {}
        if os.path.isfile(SETTINGS_PATH):
            try:
                f = open(SETTINGS_PATH, 'r', encoding='utf-8')
                data = json.load(f)
                f.close()
            except Exception as e:
                self.ctx.log('오류', 'settings.json 읽기 실패 : %s' % e)
        for name, tab in self.tabs.items():
            tab.setcfg(data.get(name) or {})

    def savesettings(self):
        data = dict((name, tab.getcfg()) for name, tab in self.tabs.items())
        try:
            f = open(SETTINGS_PATH, 'w', encoding='utf-8')
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.close()
            self.ctx.log('정보', '설정 저장 : settings.json')
        except Exception as e:
            self.ctx.log('오류', '설정 저장 실패 : %s' % e)

    def onclose(self):
        self.ctx.stopreq.set()
        self.savesettings()
        self.disconnect()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
