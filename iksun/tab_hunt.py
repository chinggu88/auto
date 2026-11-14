#iksun/tab_hunt.py - 사냥 탭 (선택)
#
#  6.1 타겟 찾기 : 메모리 엔티티 테이블에서 살아 있는 대상 몹을 가까운 순으로 고른다
#  6.2 공격 방식 : 마법 공격 - 대상 id 를 메모리에 쓰고 그 마법이 든 단축키를 누른다 (memcast.py)
#  6.3 막힘 대처 : n 번 연속 못 잡으면 새로고침 키, 사냥 시간 제한이 지나면 귀환 키 후 정지
#
#  근접(클릭) 공격은 게임 좌표를 화면 좌표로 바꾸는 캘리브레이션이 있어야 해서 아직 넣지 않았다.
#  내정보 탭에서 '사냥' 모드를 골랐을 때만 돈다.

import time
import tkinter as tk
from tkinter import ttk

KEYS = ['F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12']

#던전별 대상 몹 목록. 이름 비교는 띄어쓰기를 무시하므로 한 가지 표기만 적는다
PRESETS = {
    '오만 4층 (죽음)': ['죽음의 구울', '죽음의 크리쳐', '죽음의 유령(블루)', '죽음의 유령(레드)',
                        '죽음의 좀비', '죽음의 해골 근위병', '죽음의 해골 돌격병', '죽음의 해골 저격병'],
    '오만 9층 (불멸)': ['불멸의 네크로맨서', '불멸의 해골 기사', '불멸의 해골 돌격병',
                        '불멸의 스파토이', '불멸의 해골 저격병', '불멸의 해골 근위병'],
    '칠흑의 해골':     ['칠흑의 해골 돌격병', '칠흑의 해골 저격병', '칠흑의 해골 근위병'],
    '그림자신전 3층 (야히 근위병)': ['야히의 근위병(데몬)', '야히의 근위병(베레스)', '야히의 근위병(서큐버스)'],
}


def norm(s):
    return (s or '').replace(' ', '')


def splitnames(text):
    return [x.strip() for x in text.replace('\n', ',').split(',') if x.strip() != '']


#엔티티 테이블 raw 좌표 -> 게임 좌표 (turnundead_mem.raw_to_game 과 같다)
def raw_to_game(rx, ry):
    return ((rx & 0xFFFF) + 32768) // 2, ry


class HuntTab(ttk.Frame):
    def __init__(self, parent, app):
        ttk.Frame.__init__(self, parent, padding=12)
        self.app = app
        self.ctx = app.ctx

        #--- 6.1 타겟 찾기 ---
        box = ttk.LabelFrame(self, text='타겟 찾기 (메모리 엔티티 테이블)', padding=8)
        box.pack(fill='x')
        row = ttk.Frame(box)
        row.pack(fill='x')
        ttk.Label(row, text='목록 불러오기', width=12).pack(side='left')
        self.preset = ttk.Combobox(row, values=list(PRESETS.keys()), state='readonly', width=28)
        self.preset.pack(side='left')
        ttk.Button(row, text='넣기', command=self.onpreset).pack(side='left', padx=4)
        ttk.Button(row, text='주변 이름 보기', command=self.showaround).pack(side='left')

        ttk.Label(box, text='대상 몹 (쉼표로 구분, 띄어쓰기 무시)').pack(anchor='w', pady=(8, 2))
        self.targets = tk.Text(box, height=4, wrap='word', bg=app.colors['surface-raised'],
                               fg=app.colors['ink'], insertbackground=app.colors['ink'], relief='flat')
        self.targets.pack(fill='x')
        ttk.Label(box, text='제외 몹 (보스처럼 건드리면 안 되는 몹)').pack(anchor='w', pady=(8, 2))
        self.exclude = tk.StringVar(value='')
        ttk.Entry(box, textvariable=self.exclude).pack(fill='x')
        row = ttk.Frame(box)
        row.pack(fill='x', pady=(8, 0))
        ttk.Label(row, text='탐지 거리', width=12).pack(side='left')
        self.dist = tk.StringVar(value='10')
        ttk.Entry(row, textvariable=self.dist, width=6).pack(side='left')
        ttk.Label(row, text='게임 거리 (칸)', style='Muted.TLabel').pack(side='left', padx=4)

        #--- 6.2 공격 방식 ---
        box = ttk.LabelFrame(self, text='공격 방식 (마법)', padding=8)
        box.pack(fill='x', pady=(8, 0))
        row = ttk.Frame(box)
        row.pack(fill='x')
        ttk.Label(row, text='마법 이름', width=12).pack(side='left')
        self.spell = tk.StringVar(value='턴언데드')
        self.spellbox = ttk.Combobox(row, textvariable=self.spell, width=20)
        self.spellbox.pack(side='left')
        ttk.Button(row, text='배운 마법 불러오기', command=self.loadspells).pack(side='left', padx=4)
        row = ttk.Frame(box)
        row.pack(fill='x', pady=(6, 0))
        ttk.Label(row, text='시전 간격', width=12).pack(side='left')
        self.gap = tk.StringVar(value='0.3')
        ttk.Entry(row, textvariable=self.gap, width=6).pack(side='left')
        ttk.Label(row, text='초', style='Muted.TLabel').pack(side='left', padx=4)
        ttk.Label(box, text='그 마법이 단축키(F5~F12)에 올라가 있어야 하고, 게임 창이 맨 앞이어야 한다',
                  style='Muted.TLabel').pack(anchor='w', pady=(6, 0))

        #--- 6.3 막힘 대처 ---
        box = ttk.LabelFrame(self, text='막힘 대처', padding=8)
        box.pack(fill='x', pady=(8, 0))
        row = ttk.Frame(box)
        row.pack(fill='x')
        ttk.Label(row, text='새로고침 키', width=12).pack(side='left')
        self.refkey = tk.StringVar(value='')
        ttk.Combobox(row, textvariable=self.refkey, values=[''] + KEYS, width=5,
                     state='readonly').pack(side='left')
        self.misses = tk.StringVar(value='30')
        ttk.Entry(row, textvariable=self.misses, width=5).pack(side='left', padx=(12, 4))
        ttk.Label(row, text='바퀴 연속 대상이 없으면 누른다 (한 번이라도 잡으면 초기화)',
                  style='Muted.TLabel').pack(side='left')
        row = ttk.Frame(box)
        row.pack(fill='x', pady=(6, 0))
        ttk.Label(row, text='사냥 시간', width=12).pack(side='left')
        self.limit = tk.StringVar(value='0')
        ttk.Entry(row, textvariable=self.limit, width=6).pack(side='left')
        ttk.Label(row, text='분 후 귀환 키를 누르고 정지 (0 = 제한 없음)  귀환 키',
                  style='Muted.TLabel').pack(side='left', padx=4)
        self.retkey = tk.StringVar(value='F12')
        ttk.Combobox(row, textvariable=self.retkey, values=KEYS, width=5,
                     state='readonly').pack(side='left')

        self.lastcast = 0.0
        self.miss = 0

    #--- 화면 동작 ---

    def onpreset(self):
        names = PRESETS.get(self.preset.get())
        if not names:
            return
        have = splitnames(self.targets.get('1.0', 'end'))
        merged = have + [n for n in names if norm(n) not in set(norm(h) for h in have)]
        self.targets.delete('1.0', 'end')
        self.targets.insert('1.0', ', '.join(merged))

    #주변 엔티티 이름을 로그에 찍는다 (대상 이름을 정확히 적기 위해)
    def showaround(self):
        mem = self.ctx.mem
        if mem == None or not mem.attached():
            self.ctx.log('오류', '주변 이름 보기 : 게임에 연결되지 않았다')
            return
        objs = mem.entity_table()[0]
        names = sorted(set(o.get('name') for o in objs if o.get('name')))
        self.ctx.log('정보', '주변 %d종 : %s' % (len(names), ', '.join(names)))

    def loadspells(self):
        mem = self.ctx.mem
        if mem == None or not mem.attached():
            self.ctx.log('오류', '배운 마법 불러오기 : 게임에 연결되지 않았다')
            return
        spells = mem.spell_table()[0]
        names = [s['name'] for s in spells if s.get('name')]
        self.spellbox.configure(values=names)
        self.ctx.log('정보', '배운 마법 %d개를 불러왔다' % len(names))

    #--- 실행 ---

    def _num(self, s, default):
        try:
            return float(s)
        except Exception:
            return default

    def precheck(self, ctx):
        if len(splitnames(self.targets.get('1.0', 'end'))) == 0:
            return '사냥 탭의 대상 몹이 비어 있다 (비워 두면 플레이어까지 노릴 수 있어서 막는다)'
        if self.spell.get().strip() == '':
            return '사냥 탭의 마법 이름이 비어 있다'
        if ctx.mem.selfpos() == None:
            return '내 좌표(self_x/self_y)를 못 읽어서 거리를 잴 수 없다'
        return None

    #시작할 때 설정을 복사해 둔다. 작업 스레드는 tkinter 변수를 건드리지 않고 이 값만 쓴다
    def begin(self, ctx):
        self.run = self.getcfg()
        self.lastcast = 0.0
        self.miss = 0
        self.want = set(norm(n) for n in self.run['targets'])
        self.skip = set(norm(n) for n in self.run['exclude'])

    #가장 가까운 살아 있는 대상 하나. 없으면 None
    def pick(self, ctx):
        me = ctx.mem.selfpos()
        if me == None:
            return None
        maxd = self._num(self.run['dist'], 10)
        best, bestd = None, None
        for o in ctx.mem.entity_table()[0]:
            n = norm(o.get('name'))
            if n == '' or n not in self.want or n in self.skip or o.get('dead'):
                continue
            gx, gy = raw_to_game(o['x'], o['y'])
            d = max(abs(gx - me[0]), abs(gy - me[1]))
            if d <= maxd and (bestd == None or d < bestd):
                best, bestd = o, d
        return best

    def tick(self, ctx, info):
        now = time.time()
        run = self.run
        limit = self._num(run['limit'], 0)
        if limit > 0 and now - ctx.started >= limit * 60:
            ctx.log('트리거', '사냥 시간 %d분 지남' % limit)
            ctx.press(run['retkey'], '사냥 시간 제한')
            ctx.requeststop('사냥 시간 제한')
            return
        if now - self.lastcast < self._num(run['gap'], 0.3):
            return

        target = self.pick(ctx)
        if target == None:
            self.miss += 1
            need = int(self._num(run['misses'], 0))
            if run['refkey'] and need > 0 and self.miss >= need:
                self.miss = 0
                ctx.press(run['refkey'], '%d바퀴 연속 대상 없음' % need)
            return
        self.miss = 0
        self.lastcast = now
        ctx.cast(target, run['spell'].strip())

    #--- 설정 ---

    def getcfg(self):
        return {'targets': splitnames(self.targets.get('1.0', 'end')),
                'exclude': splitnames(self.exclude.get()),
                'dist': self.dist.get(), 'spell': self.spell.get(), 'gap': self.gap.get(),
                'refkey': self.refkey.get(), 'misses': self.misses.get(),
                'limit': self.limit.get(), 'retkey': self.retkey.get()}

    def setcfg(self, d):
        self.targets.delete('1.0', 'end')
        self.targets.insert('1.0', ', '.join(d.get('targets') or []))
        self.exclude.set(', '.join(d.get('exclude') or []))
        for key, var, default in (('dist', self.dist, '10'), ('spell', self.spell, '턴언데드'),
                                  ('gap', self.gap, '0.3'), ('refkey', self.refkey, ''),
                                  ('misses', self.misses, '30'), ('limit', self.limit, '0'),
                                  ('retkey', self.retkey, 'F12')):
            var.set(str(d.get(key, default)))
