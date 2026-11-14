#iksun/tab_buff.py - 버프 탭 (필수)
#
#  5.1 버프 슬롯 : F5~F12 칸마다 사용 / 주기(초) / 시작 시 한 번
#  5.2 생존 트리거 : 위에서부터 우선순위. 더 높은 트리거가 걸리면 아래는 건너뛴다
#
#  어느 모드(사냥/쫄)에서든 항상 함께 돈다. 작업 스레드가 매 바퀴 survive() -> dobuffs() 순서로 부른다.
#  판단에 필요한 메모리 값을 못 읽으면 동작을 멈춘다 (이미지 감지로 돌아가지 않는다).

import time
import tkinter as tk
from tkinter import ttk

import memread as mr

KEYS       = ['F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12']
HOTKEY_LEN = 0x30       #단축키 칸 하나의 이름 바이트 수 (mem.json _cast 참고)

#생존 트리거 : (id, 이름, 기준 라벨, 기본 기준값, 기본 키, 동작, 기본 켜짐)
#  동작 'stop' = 키를 누르고 멈춘다 / 'press' = 키만 누르고 계속 / 'halt' = 키 없이 멈춘다
TRIGGERS = [
    ('hostile', '적대 혈맹 등장', '',              None, 'F8',  'stop',  False),
    ('hp_low',  'HP 위험',        'HP % 이하',     30,   'F12', 'stop',  True),
    ('hp_pot',  'HP 물약',        'HP % 이하',     60,   'F7',  'press', True),
    ('mp_low',  'MP 부족',        'MP % 이하',     0,    'F12', 'stop',  False),
    ('weight',  '무게 초과',      '무게 % 이상',   82,   'F12', 'stop',  False),
    ('food',    '포만도 부족',    '포만도 % 이하', 20,   'F6',  'press', False),
    ('dead',    '사망',           'HP 0',          None, '',    'halt',  True),
]
PRESS_GAP = 3.0         #'press' 트리거를 다시 누르기까지 최소 간격(초). 물약 연타 방지


class BuffTab(ttk.Frame):
    def __init__(self, parent, app):
        ttk.Frame.__init__(self, parent, padding=12)
        self.app  = app
        self.ctx  = app.ctx
        self.last = {}          #키 또는 트리거 id -> 마지막으로 누른 시각

        #--- 5.1 버프 슬롯 ---
        box = ttk.LabelFrame(self, text='버프 슬롯 (F5 ~ F12)', padding=8)
        box.pack(fill='x')
        for c, t in enumerate(['키', '칸 내용 (메모리)', '사용', '주기(초)', '시작 시 한 번']):
            ttk.Label(box, text=t, style='Muted.TLabel').grid(row=0, column=c, sticky='w', padx=4)
        self.slots = {}
        for r, key in enumerate(KEYS, start=1):
            v = {'use': tk.BooleanVar(value=False), 'sec': tk.StringVar(value='600'),
                 'once': tk.BooleanVar(value=False)}
            ttk.Label(box, text=key, width=4, style='Mono.TLabel').grid(row=r, column=0, sticky='w', padx=4)
            v['name'] = ttk.Label(box, text='-', width=22)
            v['name'].grid(row=r, column=1, sticky='w', padx=4)
            ttk.Checkbutton(box, variable=v['use']).grid(row=r, column=2, padx=4)
            ttk.Entry(box, textvariable=v['sec'], width=7).grid(row=r, column=3, sticky='w', padx=4)
            ttk.Checkbutton(box, variable=v['once']).grid(row=r, column=4, padx=4)
            self.slots[key] = v
        ttk.Button(box, text='칸 내용 읽기', command=self.readslots).grid(
            row=len(KEYS) + 1, column=0, columnspan=2, sticky='w', pady=(6, 0))
        ttk.Label(box, text='버프를 누르는 동안에는 사냥·쫄 동작을 잠시 멈춘다', style='Muted.TLabel').grid(
            row=len(KEYS) + 1, column=2, columnspan=3, sticky='w', pady=(6, 0))

        #--- 5.2 생존 트리거 ---
        box = ttk.LabelFrame(self, text='생존 트리거 (위에서부터 우선)', padding=8)
        box.pack(fill='x', pady=(8, 0))
        for c, t in enumerate(['사용', '트리거', '기준', '값', '키', '동작']):
            ttk.Label(box, text=t, style='Muted.TLabel').grid(row=0, column=c, sticky='w', padx=4)
        self.trig = {}
        for r, (tid, name, unit, val, key, act, on) in enumerate(TRIGGERS, start=1):
            v = {'use': tk.BooleanVar(value=on), 'val': tk.StringVar(value='' if val == None else str(val)),
                 'key': tk.StringVar(value=key)}
            ttk.Checkbutton(box, variable=v['use']).grid(row=r, column=0, padx=4)
            ttk.Label(box, text=name, width=12).grid(row=r, column=1, sticky='w', padx=4)
            ttk.Label(box, text=unit, style='Muted.TLabel', width=12).grid(row=r, column=2, sticky='w', padx=4)
            if val != None:
                ttk.Entry(box, textvariable=v['val'], width=5).grid(row=r, column=3, sticky='w', padx=4)
            if act != 'halt':
                ttk.Combobox(box, textvariable=v['key'], values=KEYS, width=5,
                             state='readonly').grid(row=r, column=4, sticky='w', padx=4)
            what = {'stop': '키 누르고 정지', 'press': '키 누르고 계속', 'halt': '로그 후 정지'}[act]
            ttk.Label(box, text=what, style='Muted.TLabel').grid(row=r, column=5, sticky='w', padx=4)
            self.trig[tid] = v

        row = ttk.Frame(box)
        row.grid(row=len(TRIGGERS) + 1, column=0, columnspan=6, sticky='we', pady=(8, 0))
        ttk.Label(row, text='내 혈맹', width=8).pack(side='left')
        self.clans = tk.StringVar(value='')
        ttk.Entry(row, textvariable=self.clans).pack(side='left', fill='x', expand=True)
        ttk.Label(box, text='쉼표로 여러 개. 여기 없는 혈맹의 캐릭터가 보이면 적대로 본다',
                  style='Muted.TLabel').grid(row=len(TRIGGERS) + 2, column=0, columnspan=6, sticky='w')

    #--- 단축키 칸 이름 (메모리) ---

    def readslots(self):
        mem = self.ctx.mem
        if mem == None or not mem.attached():
            self.ctx.log('오류', '칸 내용 읽기 : 게임에 연결되지 않았다')
            return
        chains = mem.cfg.get('chains') or {}
        nspec, fspec = chains.get('hotkey_names'), chains.get('hotkey_flags')
        with mem.lock:
            naddr = mem.resolve(nspec) if nspec else None
            faddr = mem.resolve(fspec) if fspec else None
            names = mr.readmem(mem.h, naddr, HOTKEY_LEN * len(KEYS)) if naddr else None
            flags = mr.readmem(mem.h, faddr, len(KEYS)) if faddr else None
        for i, key in enumerate(KEYS):
            text = '-'
            if names != None:
                raw = names[i * HOTKEY_LEN:(i + 1) * HOTKEY_LEN]
                nm = mr._decode_name(raw)
                if nm:
                    kind = '' if flags == None else ('마법 · ' if flags[i] == 0 else '아이템 · ')
                    text = kind + nm
            self.slots[key]['name'].configure(text=text)

    #--- 실행 ---

    def _num(self, s, default=None):
        try:
            return float(s)
        except Exception:
            return default

    def precheck(self, ctx):
        for tid, name, unit, val, key, act, on in TRIGGERS:
            v = self.trig[tid]
            if not v['use'].get():
                continue
            if val != None and self._num(v['val'].get()) == None:
                return '생존 트리거 [%s] 의 값이 숫자가 아니다' % name
            if act != 'halt' and v['key'].get() not in KEYS:
                return '생존 트리거 [%s] 의 키를 고르지 않았다' % name
        if self.trig['hostile']['use'].get():
            o = ctx.mem.cfg.get('objlist') or {}
            if mr.num(o.get('base')) == None or mr.num(o.get('stride')) == None or not o.get('player_types'):
                return '적대 혈맹 트리거를 켰지만 mem.json 의 objlist(base/stride/player_types)가 비어 있다'
        for key, v in self.slots.items():
            if v['use'].get() and (self._num(v['sec'].get(), 0) or 0) <= 0:
                return '버프 슬롯 %s 의 주기가 0 이하다' % key
        return None

    #시작할 때 설정을 복사해 둔다. 작업 스레드는 tkinter 변수를 건드리지 않고 이 값만 쓴다
    def begin(self, ctx):
        self.run = self.getcfg()
        self.last = {}
        now = time.time()
        for key, s in self.run['slots'].items():
            if s['use']:
                #'시작 시 한 번' 이면 첫 바퀴에 바로 누르고, 아니면 한 주기 뒤에 누른다
                self.last[key] = 0 if s['once'] else now

    #적대 혈맹 판단. (판단됨, 적대 캐릭터) - 못 읽으면 (False, None)
    def _hostile(self, ctx):
        mem = ctx.mem
        objs = mem.objects()
        plrs = mem.players(objs)
        if len(objs) == 0 or len(plrs) == 0:       #나도 플레이어이므로 비면 '못 읽음' 이다
            return False, None
        mine = self.run['clans']
        me = mem.selfid()
        for o in plrs:
            if me != None and o.get('id') == me:
                continue
            clan = (o.get('clan') or '').strip()
            if clan != '' and clan not in mine:
                return True, o
        return True, None

    #생존 트리거. 'stop' = 멈췄다 / 'acted' = 키를 눌렀다 / None = 아무것도 안 함
    def survive(self, ctx, info):
        hp, hpm = info.get('hp'), info.get('hp_max')
        mp, mpm = info.get('mp'), info.get('mp_max')
        hppct = hp * 100.0 / hpm if hpm else None
        mppct = mp * 100.0 / mpm if (mp != None and mpm) else None
        now = time.time()

        for tid, name, unit, val, defkey, act, on in TRIGGERS:
            v = self.run['triggers'][tid]
            if not v['use']:
                continue
            limit = self._num(v['val'])
            key = v['key']
            hit, why = False, ''
            if tid == 'hostile':
                judged, who = self._hostile(ctx)
                if not judged:
                    ctx.requeststop('적대 혈맹을 판단할 수 없다 (주변 목록을 못 읽음)')
                    return 'stop'
                hit = who != None
                why = '적대 캐릭터 %s (%s)' % (who.get('name'), who.get('clan')) if hit else ''
            elif tid in ('hp_low', 'hp_pot'):
                hit = hppct != None and hppct <= limit
                why = 'HP %.0f%% <= %s%%' % (hppct, v['val']) if hit else ''
            elif tid == 'mp_low':
                if limit and limit > 0:
                    if mppct == None:
                        ctx.requeststop('MP 를 못 읽음 (판단불가)')
                        return 'stop'
                    hit = mppct <= limit
                    why = 'MP %.0f%% <= %s%%' % (mppct, v['val']) if hit else ''
            elif tid == 'weight':
                w = info.get('weight_pct')
                hit = w != None and w >= limit
                why = '무게 %s%% >= %s%%' % (w, v['val']) if hit else ''
            elif tid == 'food':
                f = info.get('food_pct')
                hit = f != None and f <= limit
                why = '포만도 %s%% <= %s%%' % (f, v['val']) if hit else ''
            elif tid == 'dead':
                hit = hp == 0
                why = 'HP 0'
            if not hit:
                continue

            ctx.log('트리거', '%s : %s' % (name, why))
            if act == 'halt':
                ctx.requeststop(name)
                return 'stop'
            if act == 'stop':
                ctx.press(key, name)
                ctx.requeststop(name)
                return 'stop'
            if now - self.last.get(tid, 0) >= PRESS_GAP:
                self.last[tid] = now
                ctx.press(key, name)
                return 'acted'
        return None

    #버프 주기. 키를 하나라도 눌렀으면 True (그 바퀴는 사냥·쫄을 쉰다)
    def dobuffs(self, ctx):
        now = time.time()
        for key in KEYS:
            v = self.run['slots'][key]
            if not v['use']:
                continue
            sec = self._num(v['sec'], 0) or 0
            if sec > 0 and now - self.last.get(key, now) >= sec:
                self.last[key] = now
                ctx.press(key, '버프 주기 %d초' % sec)
                return True
        return False

    #--- 설정 ---

    def getcfg(self):
        return {
            'slots': dict((k, {'use': v['use'].get(), 'sec': v['sec'].get(), 'once': v['once'].get()})
                          for k, v in self.slots.items()),
            'triggers': dict((t, {'use': v['use'].get(), 'val': v['val'].get(), 'key': v['key'].get()})
                             for t, v in self.trig.items()),
            'clans': [x.strip() for x in self.clans.get().split(',') if x.strip() != ''],
        }

    def setcfg(self, d):
        for k, s in (d.get('slots') or {}).items():
            if k in self.slots:
                self.slots[k]['use'].set(bool(s.get('use')))
                self.slots[k]['sec'].set(str(s.get('sec', '600')))
                self.slots[k]['once'].set(bool(s.get('once')))
        for t, s in (d.get('triggers') or {}).items():
            if t in self.trig:
                self.trig[t]['use'].set(bool(s.get('use')))
                self.trig[t]['val'].set(str(s.get('val', '')))
                self.trig[t]['key'].set(str(s.get('key', '')))
        self.clans.set(', '.join(d.get('clans') or []))
