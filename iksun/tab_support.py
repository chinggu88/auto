#iksun/tab_support.py - 쫄 탭 (선택)
#
#  7.1 대상 지정 : 서포트할 캐릭터 이름. 쉼표로 여러 명을 적으면 돌아가며 준다 (대상 그룹)
#  7.2 지원 마법 : 마법마다 주기(초)를 정해 대상에게 시전한다 (memcast.py, 마우스 안 씀)
#  7.3 따라가기 : 대상과의 거리를 표시하고, 기준 거리를 넘으면 로그로 알린다
#
#  아직 안 되는 것 (기획서 미결 사항)
#   - 대상 HP 조건 : 엔티티 +0x50 은 HP 가 아니라서(memread.py 주석) 대상 HP 를 못 읽는다
#   - 실제 이동 : 게임 좌표 -> 화면 좌표 캘리브레이션이 필요해서 거리 경고까지만 한다
#  내정보 탭에서 '쫄' 모드를 골랐을 때만 돈다.

import time
import tkinter as tk
from tkinter import ttk

SPELL_ROWS = 4          #지원 마법 줄 수
LOST_LOG   = 10.0       #대상을 못 찾았을 때 같은 로그를 다시 남기기까지 간격(초)


def norm(s):
    return (s or '').replace(' ', '')


def splitnames(text):
    return [x.strip() for x in text.split(',') if x.strip() != '']


def raw_to_game(rx, ry):
    return ((rx & 0xFFFF) + 32768) // 2, ry


class SupportTab(ttk.Frame):
    def __init__(self, parent, app):
        ttk.Frame.__init__(self, parent, padding=12)
        self.app = app
        self.ctx = app.ctx

        #--- 7.1 대상 지정 ---
        box = ttk.LabelFrame(self, text='대상 지정', padding=8)
        box.pack(fill='x')
        row = ttk.Frame(box)
        row.pack(fill='x')
        ttk.Label(row, text='대상 캐릭터', width=12).pack(side='left')
        self.target = tk.StringVar(value='')
        ttk.Entry(row, textvariable=self.target).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='주변 플레이어 보기', command=self.showaround).pack(side='left', padx=(4, 0))
        ttk.Label(box, text='쉼표로 여러 명을 적으면 한 명씩 돌아가며 시전한다',
                  style='Muted.TLabel').pack(anchor='w', pady=(4, 0))
        row = ttk.Frame(box)
        row.pack(fill='x', pady=(6, 0))
        ttk.Label(row, text='제외 캐릭터', width=12).pack(side='left')
        self.exclude = tk.StringVar(value='')
        ttk.Entry(row, textvariable=self.exclude).pack(side='left', fill='x', expand=True)
        self.status = ttk.Label(box, text='대상 : -', style='Mono.TLabel')
        self.status.pack(anchor='w', pady=(6, 0))

        #--- 7.2 지원 마법 ---
        box = ttk.LabelFrame(self, text='지원 마법', padding=8)
        box.pack(fill='x', pady=(8, 0))
        for c, t in enumerate(['사용', '마법 이름', '주기(초)']):
            ttk.Label(box, text=t, style='Muted.TLabel').grid(row=0, column=c, sticky='w', padx=4)
        self.rows = []
        for r in range(SPELL_ROWS):
            v = {'use': tk.BooleanVar(value=(r == 0)),
                 'spell': tk.StringVar(value='아이언 스킨' if r == 0 else ''),
                 'sec': tk.StringVar(value='60')}
            ttk.Checkbutton(box, variable=v['use']).grid(row=r + 1, column=0, padx=4)
            v['box'] = ttk.Combobox(box, textvariable=v['spell'], width=20)
            v['box'].grid(row=r + 1, column=1, sticky='w', padx=4)
            ttk.Entry(box, textvariable=v['sec'], width=6).grid(row=r + 1, column=2, sticky='w', padx=4)
            self.rows.append(v)
        ttk.Button(box, text='배운 마법 불러오기', command=self.loadspells).grid(
            row=SPELL_ROWS + 1, column=0, columnspan=2, sticky='w', pady=(6, 0))
        ttk.Label(box, text='대상 HP 조건(힐)은 대상 HP 를 메모리에서 못 읽어 아직 없다',
                  style='Muted.TLabel').grid(row=SPELL_ROWS + 2, column=0, columnspan=3, sticky='w')

        #--- 7.3 따라가기 ---
        box = ttk.LabelFrame(self, text='따라가기', padding=8)
        box.pack(fill='x', pady=(8, 0))
        row = ttk.Frame(box)
        row.pack(fill='x')
        ttk.Label(row, text='기준 거리', width=12).pack(side='left')
        self.follow = tk.StringVar(value='8')
        ttk.Entry(row, textvariable=self.follow, width=5).pack(side='left')
        ttk.Label(row, text='칸을 넘으면 로그로 알린다 (자동 이동은 캘리브레이션 후)',
                  style='Muted.TLabel').pack(side='left', padx=4)

        self.statustext = '대상 : -'   #작업 스레드가 쓰고 화면 스레드가 0.5초마다 옮긴다
        self.after(500, self.showstatus)
        self.last = {}          #(대상 이름, 마법) -> 마지막 시전 시각
        self.turn = 0           #대상 그룹에서 다음 차례
        self.lostlog = 0.0
        self.farlog = 0.0

    #--- 화면 동작 ---

    def showstatus(self):
        self.status.configure(text=self.statustext)
        self.after(500, self.showstatus)

    def showaround(self):
        mem = self.ctx.mem
        if mem == None or not mem.attached():
            self.ctx.log('오류', '주변 플레이어 보기 : 게임에 연결되지 않았다')
            return
        names = sorted(set(o.get('name') for o in mem.entity_table()[0] if o.get('name')))
        self.ctx.log('정보', '주변 이름 %d개 : %s' % (len(names), ', '.join(names)))

    def loadspells(self):
        mem = self.ctx.mem
        if mem == None or not mem.attached():
            self.ctx.log('오류', '배운 마법 불러오기 : 게임에 연결되지 않았다')
            return
        names = [s['name'] for s in mem.spell_table()[0] if s.get('name')]
        for v in self.rows:
            v['box'].configure(values=names)
        self.ctx.log('정보', '배운 마법 %d개를 불러왔다' % len(names))

    #--- 실행 ---

    def _num(self, s, default):
        try:
            return float(s)
        except Exception:
            return default

    #켠 마법 [(이름, 주기)]. cfg 를 주면 그 복사본에서 읽는다 (작업 스레드용)
    def spells(self, cfg=None):
        rows = (cfg or self.getcfg())['spells']
        return [(r['spell'].strip(), self._num(r['sec'], 0))
                for r in rows if r['use'] and r['spell'].strip() != '']

    def precheck(self, ctx):
        if len(splitnames(self.target.get())) == 0:
            return '쫄 탭의 대상 캐릭터가 비어 있다'
        if len(self.spells()) == 0:
            return '쫄 탭에서 켠 지원 마법이 없다'
        for name, sec in self.spells():
            if sec <= 0:
                return '지원 마법 [%s] 의 주기가 0 이하다' % name
        return None

    #시작할 때 설정을 복사해 둔다. 작업 스레드는 tkinter 변수·위젯을 건드리지 않고 이 값만 쓴다
    def begin(self, ctx):
        self.run = self.getcfg()
        self.runspells = self.spells(self.run)
        self.last = {}
        self.turn = 0
        self.lostlog = 0.0
        self.farlog = 0.0

    def tick(self, ctx, info):
        now = time.time()
        skip = set(norm(x) for x in self.run['exclude'])
        names = [n for n in self.run['target'] if norm(n) not in skip]
        if len(names) == 0:
            return
        name = names[self.turn % len(names)]
        self.turn += 1

        found = None
        for o in ctx.mem.entity_table()[0]:
            if norm(o.get('name')) == norm(name) and not o.get('dead'):
                found = o
                break
        if found == None:
            self.statustext = '대상 : %s - 화면에 없음' % name
            if now - self.lostlog >= LOST_LOG:
                self.lostlog = now
                ctx.log('정보', '대상 %s 를 주변에서 못 찾았다 - 기다린다' % name)
            return

        me = ctx.mem.selfpos()
        dist = None
        if me != None:
            gx, gy = raw_to_game(found['x'], found['y'])
            dist = max(abs(gx - me[0]), abs(gy - me[1]))
        self.statustext = '대상 : %s  거리 %s' % (name, '-' if dist == None else dist)
        limit = self._num(self.run['follow'], 0)
        if dist != None and limit > 0 and dist > limit and now - self.farlog >= LOST_LOG:
            self.farlog = now
            ctx.log('트리거', '대상 %s 가 %d칸 떨어졌다 (기준 %d칸)' % (name, dist, limit))

        #주기가 된 마법 하나만 이번 바퀴에 시전한다
        for spell, sec in self.runspells:
            if now - self.last.get((name, spell), 0) >= sec:
                r = ctx.cast(found, spell)
                if r != None and r.get('state') == 'sent':
                    self.last[(name, spell)] = now
                break

    #--- 설정 ---

    def getcfg(self):
        return {'target': splitnames(self.target.get()),
                'exclude': splitnames(self.exclude.get()),
                'spells': [{'use': v['use'].get(), 'spell': v['spell'].get(), 'sec': v['sec'].get()}
                           for v in self.rows],
                'follow': self.follow.get()}

    def setcfg(self, d):
        self.target.set(', '.join(d.get('target') or []))
        self.exclude.set(', '.join(d.get('exclude') or []))
        for v, s in zip(self.rows, d.get('spells') or []):
            v['use'].set(bool(s.get('use')))
            v['spell'].set(str(s.get('spell', '')))
            v['sec'].set(str(s.get('sec', '60')))
        self.follow.set(str(d.get('follow', '8')))
