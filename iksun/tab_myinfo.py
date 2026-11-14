#iksun/tab_myinfo.py - 내정보 탭 (필수)
#
#  게임 연결 확인, 연결된 캐릭터 정보, 모드(사냥/쫄) 선택과 시작/정지, 로그.
#  캐릭터 정보는 memread.charinfo() 를 1초마다 읽는다 (실행 중에는 작업 스레드가 읽은 값을 쓴다).

import tkinter as tk
from tkinter import ttk

import memread as mr

LOG_KINDS = ['전체', '행동', '트리거', '오류', '정보']
LOG_MAX   = 2000        #화면에 남기는 로그 줄 수

#캐릭터 정보 표 : (라벨, charinfo 를 받아 글자를 돌려주는 함수)
def _f(v):
    return '-' if v == None else str(v)

INFO_ROWS = [
    ('이름',       lambda c: _f(c.get('name'))),
    ('레벨',       lambda c: 'LEV %s' % _f(c.get('level'))),
    ('경험치',     lambda c: '%s%%' % _f(c.get('exp_pct'))),
    ('HP',         lambda c: '%s / %s' % (_f(c.get('hp')), _f(c.get('hp_max')))),
    ('MP',         lambda c: '%s / %s' % (_f(c.get('mp')), _f(c.get('mp_max')))),
    ('AC',         lambda c: _f(c.get('ac'))),
    ('성향',       lambda c: _f(c.get('align'))),
    ('포만도',     lambda c: '%s%%' % _f(c.get('food_pct'))),
    ('무게',       lambda c: '%s%%' % _f(c.get('weight_pct'))),
    ('스탯',       lambda c: '힘 %s 지능 %s 지혜 %s 민첩 %s 체력 %s 카리스마 %s' % tuple(
                                _f(c.get(k)) for k in ('str', 'int', 'wis', 'dex', 'con', 'cha'))),
    ('저항',       lambda c: '불 %s 물 %s 바람 %s 땅 %s' % tuple(
                                _f(c.get(k)) for k in ('fire', 'water', 'wind', 'earth'))),
]


#char_id 로 엔티티 테이블에서 내 캐릭터 이름을 찾는다. 못 찾으면 None
def findname(mem, cid):
    if cid == None:
        return None
    try:
        objs, head, count = mem.entity_table()
    except Exception:
        return None
    for o in objs:
        if o.get('id') == cid:
            return o.get('name')
    return None


class MyInfoTab(ttk.Frame):
    def __init__(self, parent, app):
        ttk.Frame.__init__(self, parent, padding=12)
        self.app  = app
        self.ctx  = app.ctx
        self.logs = []          #(시각, 종류, 내용)
        self.name = None        #캐릭터 이름 캐시 (연결마다 다시 찾는다)

        #--- 4.1 게임 연결 ---
        box = ttk.LabelFrame(self, text='게임 연결', padding=8)
        box.pack(fill='x')
        row = ttk.Frame(box)
        row.pack(fill='x')
        ttk.Label(row, text='클라이언트', width=10).pack(side='left')
        self.proc = ttk.Combobox(row, state='readonly', width=34)
        self.proc.pack(side='left', padx=(0, 8))
        ttk.Button(row, text='새로고침', command=self.refreshprocs).pack(side='left')
        ttk.Button(row, text='연결', command=self.onconnect).pack(side='left', padx=4)
        ttk.Button(row, text='해제', command=self.ondisconnect).pack(side='left')
        self.connmsg = ttk.Label(box, text='미연결', style='Idle.TLabel')
        self.connmsg.pack(anchor='w', pady=(6, 0))

        #--- 4.2 캐릭터 정보 ---
        box = ttk.LabelFrame(self, text='캐릭터 정보', padding=8)
        box.pack(fill='x', pady=(8, 0))
        self.vals = {}
        for i, (label, fn) in enumerate(INFO_ROWS):
            ttk.Label(box, text=label, width=8, style='Muted.TLabel').grid(row=i, column=0, sticky='w')
            v = ttk.Label(box, text='-', style='Mono.TLabel')
            v.grid(row=i, column=1, sticky='w')
            self.vals[label] = v
        self.extra = ttk.Label(box, text='스킬 -개 · 소지품 -개', style='Muted.TLabel')
        self.extra.grid(row=len(INFO_ROWS), column=0, columnspan=2, sticky='w', pady=(4, 0))

        #--- 4.3 실행 ---
        box = ttk.LabelFrame(self, text='실행', padding=8)
        box.pack(fill='x', pady=(8, 0))
        self.modevar = tk.StringVar(value='hunt')
        ttk.Radiobutton(box, text='사냥', value='hunt', variable=self.modevar,
                        command=self.onmode).pack(side='left')
        ttk.Radiobutton(box, text='쫄', value='support', variable=self.modevar,
                        command=self.onmode).pack(side='left', padx=(8, 16))
        self.startbtn = ttk.Button(box, text='시작하기', style='Accent.TButton', command=app.start)
        self.startbtn.pack(side='left')
        self.stopbtn = ttk.Button(box, text='정지 (Tab)', command=app.stop, state='disabled')
        self.stopbtn.pack(side='left', padx=4)
        ttk.Button(box, text='설정 저장', command=app.savesettings).pack(side='right')

        #--- 4.4 로그 ---
        box = ttk.LabelFrame(self, text='로그', padding=8)
        box.pack(fill='both', expand=True, pady=(8, 0))
        row = ttk.Frame(box)
        row.pack(fill='x')
        self.kindvar = tk.StringVar(value='전체')
        for k in LOG_KINDS:
            ttk.Radiobutton(row, text=k, value=k, variable=self.kindvar,
                            command=self.redraw).pack(side='left', padx=(0, 6))
        c = app.colors
        self.text = tk.Text(box, height=10, bg=c['surface-raised'], fg=c['ink'],
                            insertbackground=c['ink'], relief='flat', font=('Consolas', 9),
                            state='disabled', wrap='none')
        self.text.pack(fill='both', expand=True, pady=(6, 0))
        self.text.tag_configure('행동', foreground=c['state-ok'])
        self.text.tag_configure('트리거', foreground=c['state-danger'])
        self.text.tag_configure('오류', foreground=c['state-unknown'])
        self.text.tag_configure('정보', foreground=c['ink-muted'])

        self.refreshprocs()
        self.after(1000, self.refreshinfo)

    #--- 연결 ---

    def refreshprocs(self):
        try:
            #찾을 프로세스 이름은 mem.json 의 process (핏빛서버는 Lin.exe)
            m = mr.Mem(self.app.mempath)
            want = str(m.cfg.get('process', 'Lin.exe')).lower() if m.loadcfg() else 'lin.exe'
            items = ['PID %d  %s' % (p, n) for p, n in mr.procs() if n.lower() == want]
        except Exception as e:
            items = []
            self.connmsg.configure(text='프로세스 목록을 못 읽음 : %s' % e, style='Unknown.TLabel')
        self.proc.configure(values=items)
        if len(items) >= 1:
            self.proc.current(0)
        #하나뿐이면 바로 붙는다
        if len(items) == 1 and (self.ctx.mem == None or not self.ctx.mem.attached()):
            self.onconnect()

    def onconnect(self):
        sel = self.proc.get()
        pid = int(sel.split()[1]) if sel.startswith('PID ') else None
        self.name = None
        if self.app.connect(pid):
            self.connmsg.configure(text='연결됨 · 메모리 읽기 정상 (PID %d)' % self.ctx.mem.pid,
                                   style='Ok.TLabel')
        else:
            self.connmsg.configure(text='미연결 · 로그에서 이유를 확인한다', style='Unknown.TLabel')

    def ondisconnect(self):
        self.app.disconnect()
        self.name = None
        self.connmsg.configure(text='미연결', style='Idle.TLabel')

    #--- 캐릭터 정보 ---

    def refreshinfo(self):
        ctx = self.ctx
        mem = ctx.mem
        if mem != None and mem.attached():
            #실행 중이면 작업 스레드가 읽은 값을 쓰고, 아니면 여기서 읽는다
            info = ctx.info if ctx.running else None
            if info == None:
                try:
                    info = mem.charinfo()
                except Exception:
                    info = None
                ctx.info = info
            if info != None:
                if self.name == None:
                    self.name = findname(mem, info.get('id'))
                info = dict(info)
                info['name'] = self.name if self.name else '(엔티티 테이블에서 못 찾음)'
                for label, fn in INFO_ROWS:
                    self.vals[label].configure(text=fn(info))
                try:
                    spells = mem.spell_table()[0]
                    items = mem.item_table()[0]
                    self.extra.configure(text='스킬 %d개 · 소지품 %d개' % (len(spells), len(items)))
                except Exception:
                    pass
        self.after(1000, self.refreshinfo)

    #--- 실행 ---

    def onmode(self):
        self.ctx.mode = self.modevar.get()

    def setrunning(self, on):
        self.startbtn.configure(state='disabled' if on else 'normal',
                                text='동작 중  (Tab = 정지)' if on else '시작하기')
        self.stopbtn.configure(state='normal' if on else 'disabled')

    #--- 로그 ---

    def addlog(self, t, kind, text):
        self.logs.append((t, kind, text))
        if len(self.logs) > LOG_MAX:
            self.logs = self.logs[-LOG_MAX:]
            self.redraw()
            return
        if self.kindvar.get() in ('전체', kind):
            self._append(t, kind, text)

    def _append(self, t, kind, text):
        bottom = self.text.yview()[1] >= 0.999
        self.text.configure(state='normal')
        self.text.insert('end', '%s  %-3s  %s\n' % (t, kind, text), kind)
        self.text.configure(state='disabled')
        if bottom:
            self.text.see('end')        #맨 아래를 보고 있을 때만 따라 내려간다

    def redraw(self):
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.configure(state='disabled')
        want = self.kindvar.get()
        for t, kind, text in self.logs:
            if want in ('전체', kind):
                self._append(t, kind, text)

    #--- 설정 / 실행 훅 ---

    def getcfg(self):
        return {'mode': self.modevar.get()}

    def setcfg(self, d):
        self.modevar.set(d.get('mode', 'hunt'))
        self.ctx.mode = self.modevar.get()

    def precheck(self, ctx):
        return None

    def begin(self, ctx):
        pass
