#캐릭터 이름으로 캐릭터 구조체를 찾아 HP 를 짚어낸다
#
#  쓰는 법 :   python findme.py --name 캐릭터이름
#              python findme.py --anchor 2169     (최대 HP 를 기준점으로)
#              python findme.py                   (이름을 물어본다)
#
#  --anchor 는 이름이 두 글자뿐이라 채팅 곳곳에 걸리거나, 구조체에 평문 이름이 없을 때 쓴다.
#  최대 HP 는 맞아도 안 변해서 '줄어든 값' 으로는 절대 안 잡히지만, 바로 옆에 현재 HP 가
#  있을 가능성이 아주 높다. 그래서 최대 HP 를 찾아 그 옆에서 줄어드는 값을 본다.
#
#  옵션 :
#    --win 512        이름 주변 몇 바이트를 볼지 (기본 192, 앞뒤 각각)
#    --max 10         json 에 담을 자리 수 (기본 40)
#    --out 경로.json  덤프 저장 위치 (기본 findme_dump.json)
#    --dump-only      맞는 단계를 건너뛰고 지금 메모리만 덤프한다
#
#  찾은 자리 주변을 findme_dump.json 으로 통째로 남긴다.
#  자동 판정이 빗나가도 그 json 을 열어 직접 구조를 볼 수 있다 :
#    changed_summary  맞았을 때 변한 값들 - 여기부터 본다
#    fields[].off     이름이 시작하는 자리를 0 으로 본 상대 위치
#    fields[].rva     mem.json 의 base 에 그대로 넣을 값
#    fields[].u32/u16/f32  그 자리를 각 타입으로 읽은 값
#    fields[].text    그 자리부터 16바이트를 글자로 (옆 이름/혈맹명이 보인다)
#    hits[].hexdump   사람이 읽기 좋은 16진 덤프
#
#  왜 이 방법이 나은가 :
#    '값이 줄었다' 는 신호는 너무 약하다. 게임 메모리에는 줄어드는 값이 수만 개 있고
#    매초 알아서 줄어드는 타이머는 모든 라운드를 통과한다 (실제로 그것 때문에 실패했다).
#    반면 캐릭터 이름 문자열은 거의 유일해서 한 번에 몇 군데로 줄어든다.
#    그 주변이 캐릭터 구조체이므로, 맞았을 때 그 안에서 '무엇이 얼마나 줄었는지' 만
#    보면 된다. 비교 대상이 수십만 개에서 수십 개로 줄어드는 것이 핵심이다.
#
#  순서 :
#    1) 이름 문자열을 메모리에서 찾는다 (cp949 / utf-16 / utf-8 전부 시도)
#    2) 찾은 자리 주변을 통째로 기록한다
#    3) 몹한테 맞아서 HP 를 줄이고 [1] 을 누른다
#    4) 기록과 비교해 '줄어든 값' 과 '그 옆에 안 변하고 더 큰 값'(= 최대치) 을 찾는다
#    5) mem.json 에 저장하고, 맞는지 바로 확인시켜 준다
#
#  읽기 전용이다. 게임 메모리에 쓰지 않고 게임에 키/마우스도 보내지 않는다.
#
#  Windows 전용.
import json
import os
import struct
import sys
import time

import memread as mr
import memprobe as mp
import hpfind as hf

#이름이 어떤 인코딩으로 들어 있는지 모르니 전부 시도한다.
#구버전 한국 클라이언트는 cp949 가 거의 확실하지만, UI 쪽은 유니코드인 경우도 있다
ENCODINGS = [('cp949', '완성형'), ('utf-16-le', '유니코드'), ('utf-8', 'UTF-8')]

WIN      = 192      #이름 주변 몇 바이트를 볼지 (앞뒤 각각). --win 으로 바꾼다
MAX_HITS = 400      #이름이 너무 많이 나오면 자른다
MAX_DUMP = 40       #json 으로 뽑을 자리 수 상한. --max 로 바꾼다
DUMP_NAME = 'findme_dump.json'
TYPES    = ['u32', 'u16']

#HP 로 말이 되는 범위와, 한 대 맞아서 줄어들 수 있는 폭
HP_MIN, HP_MAX = 1, 1000000
HIT_MIN, HIT_MAX = 1, 200000


def say(s=''):
    print(s)
    sys.stdout.flush()


def line():
    say('=' * 70)


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


#=====================================================================
# 1. 이름 찾기
#=====================================================================

#이름 문자열이 들어 있는 자리를 전부 찾는다. [(주소, 인코딩), ...]
#  1차 : 이름 바로 뒤에 NUL 이 붙은 것만 (구조체의 이름 칸은 이렇게 끝난다)
#        채팅은 '[여포]:' 처럼 괄호나 글자가 따라오므로 여기서 거의 다 떨어진다.
#        두 글자 이름은 문장 곳곳에 걸려서 이 단계가 없으면 채팅 로그만 수백 개 나온다
#  2차 : 1차가 비었을 때만, NUL 조건 없이
def scanname(m, name, strict=True):
    needles = []
    for enc, label in ENCODINGS:
        try:
            b = name.encode(enc)
        except Exception:
            continue
        if len(b) >= 2 and b not in [x[0] for x in needles]:
            needles.append((b, enc, label))
    if not needles:
        say('이름을 바이트로 바꿀 수 없다 : ' + name)
        return [], False

    say('찾는 바이트 :')
    for b, enc, label in needles:
        say('    %-10s %s' % (label, ' '.join('%02X' % x for x in b)))
    say()

    def scan(wrt, nul):
        regs  = mr.regions(m.h, writable=wrt,
                           maxaddr=(1 << 32) if m.ptrsz == 4 else None)
        total = sum(r[1] for r in regs)
        say('검색 영역 %d개, %.1f MB  (%s, %s)'
            % (len(regs), total / 1048576.0,
               '쓰기 가능' if wrt else '읽기 전용 포함',
               '이름+NUL' if nul else '이름만'))
        hits = []
        capped = False
        for base, size in regs:
            for at, raw in mr.readchunks(m.h, base, size):
                for b, enc, label in needles:
                    nd  = b + (b'\x00' if nul else b'')
                    pos = raw.find(nd)
                    while pos >= 0:
                        hits.append((at + pos, enc))
                        if len(hits) >= MAX_HITS:
                            capped = True
                            break
                        pos = raw.find(nd, pos + 1)
                if capped:
                    break
            if capped:
                break
        if capped:
            say('  ! %d곳에서 끊었다. 이름이 너무 흔하다' % MAX_HITS)
        return hits

    plan = [(True, True), (False, True), (True, False), (False, False)] if strict \
           else [(True, False), (False, False)]
    for wrt, nul in plan:
        hits = scan(wrt, nul)
        if hits:
            return hits, nul
        say('  여기서는 못 찾았다')
    return [], False


#최대 HP 같은 '안 변하는 값' 을 기준점으로 쓴다. [(주소, 타입), ...]
#  이름이 두 글자뿐이거나 구조체에 평문으로 없을 때의 대안이다.
#  최대 HP 는 맞아도 안 변하므로 '줄어든 값' 검색으로는 절대 안 잡히지만,
#  그 바로 옆에 현재 HP 가 있을 가능성이 아주 높다
def scananchor(m, value):
    hits = []
    for kind in ('u16', 'u32'):
        cands, single, gaps = mp.scanall(m, kind, value, None, quiet=(kind != 'u16'))
        if cands:
            say('  %s 로 %d군데' % (kind, len(cands)))
            hits += [(a, kind) for a, v in cands]
        if len(hits) >= MAX_HITS:
            say('  ! %d곳에서 끊었다. 값이 너무 흔하다. 더 특이한 값으로' % MAX_HITS)
            hits = hits[:MAX_HITS]
            break
    return hits


#=====================================================================
# 2. 구조체 안에서 변한 값 찾기
#=====================================================================

#주소 주변을 통째로 읽어둔다. {주소: bytes}
def snapshot(m, hits):
    out = {}
    for addr, enc in hits:
        lo  = max(0, addr - WIN)
        raw = mr.readmem(m.h, lo, WIN * 2)
        if raw != None:
            out[addr] = (lo, raw)
    return out


#기록과 지금을 비교해, 줄어든 값들을 찾는다.
#돌려주는 것 : [{addr, kind, off, old, new, delta, maxaddr, maxval, name}]
def diffs(m, snaps, hits):
    enc_of = dict(hits)
    out    = []
    for addr, (lo, old) in snaps.items():
        new = mr.readmem(m.h, lo, len(old))
        if new == None:
            continue
        for kind in TYPES:
            fmt, size = mr.FMT[kind]
            for off in range(0, len(old) - size + 1, size):
                a = lo + off
                if a % size != 0:
                    continue
                o = struct.unpack_from(fmt, old, off)[0]
                n = struct.unpack_from(fmt, new, off)[0]
                if n >= o:                       #줄어든 것만 본다
                    continue
                d = o - n
                if not (HP_MIN <= n <= HP_MAX):  #HP 로 말이 안 되는 값
                    continue
                if not (HIT_MIN <= d <= HIT_MAX):
                    continue

                #바로 옆에서 '안 변했고 줄어든 값보다 큰' 값을 찾는다 = 최대치 후보
                mx, mxv = None, None
                for off2 in range(0, len(old) - size + 1, size):
                    if off2 == off:
                        continue
                    a2 = lo + off2
                    if a2 % size != 0 or abs(a2 - a) > 64:
                        continue
                    o2 = struct.unpack_from(fmt, old, off2)[0]
                    n2 = struct.unpack_from(fmt, new, off2)[0]
                    if o2 != n2 or not (o <= o2 <= HP_MAX):
                        continue
                    if mx == None or abs(a2 - a) < abs(mx - a):
                        mx, mxv = a2, o2

                out.append({'addr': a, 'kind': kind, 'name_at': addr,
                            'enc': enc_of.get(addr, ''), 'old': o, 'new': n,
                            'delta': d, 'maxaddr': mx, 'maxval': mxv,
                            'maxdist': (abs(mx - a) if mx != None else 9999),
                            'dist': a - addr})
    return out


#좋아 보이는 순서로 정렬한다.
#  1) 최대치 짝이 있는가      - 타이머에는 짝이 없다
#  2) 그 짝이 얼마나 붙어 있나 - hp 와 hp_max 는 보통 바로 옆(4~16바이트)이다.
#                               '이름과 가까운가' 보다 이쪽이 훨씬 강한 신호다.
#                               (이름 근처의 다른 감소값이 멀리 있는 상수를 짝으로
#                                잘못 집어 1순위가 되는 일이 실제로 있었다)
#  3) 이름에서 가까운가
def rank(cands):
    def key(c):
        return (0 if c['maxaddr'] != None else 1,
                c['maxdist'],
                abs(c['dist']),
                c['delta'])
    return sorted(cands, key=key)


#=====================================================================
# 구조 덤프 : 눈으로 보고 직접 찾을 수 있게 json 으로 뽑는다
#=====================================================================

#cp949 로 읽히는 글자인지 본다. (ASCII 인쇄 가능) 또는 (완성형 2바이트)
#  완성형 : 앞바이트 0x81~0xFE, 뒷바이트 0x41~0x5A / 0x61~0x7A / 0x81~0xFE
def _textlen(raw, i):
    b = raw[i]
    if 0x20 <= b < 0x7F:
        return 1
    if 0x81 <= b <= 0xFE and i + 1 < len(raw):
        c = raw[i + 1]
        if (0x41 <= c <= 0x5A) or (0x61 <= c <= 0x7A) or (0x81 <= c <= 0xFE):
            return 2
    return 0


#글자가 이어지는 구간을 찾는다. [(시작, 끝), ...]
#  4바이트씩 쪼개 보면 문장이 조각나서 읽을 수가 없다. 이어 붙여야 눈에 들어온다
def _textruns(raw, minlen=6):
    runs = []
    i = 0
    while i < len(raw):
        n = _textlen(raw, i)
        if n == 0:
            i += 1
            continue
        start = i
        while i < len(raw):
            n = _textlen(raw, i)
            if n == 0:
                break
            i += n
        if i - start >= minlen:
            runs.append((start, i))
    return runs


#창 안을 '글자 덩어리' 와 '숫자 자리' 로 나눠서 돌려준다.
#한 줄에 하나의 정보가 담기게 하는 것이 목적이다
def segments(before, after, lo, base, runs):
    inrun = [False] * len(before)
    for a, b in runs:
        for i in range(a, b):
            inrun[i] = True

    out = []
    i   = 0
    while i < len(before):
        if inrun[i]:
            j = i
            while j < len(before) and inrun[j]:
                j += 1
            try:
                txt = bytes(before[i:j]).decode('cp949', 'replace')
            except Exception:
                txt = ''
            txt = ''.join(c if c.isprintable() else ' ' for c in txt)
            out.append({'off': i - WIN, 'addr': '0x%X' % (lo + i),
                        'rva': '0x%X' % (lo + i - base) if lo + i >= base else None,
                        'kind': 'text', 'len': j - i, 'text': txt})
            i = j
            continue

        #숫자 구간 : 4바이트 정렬 자리이고, 그 4바이트가 전부 숫자 구간일 때만 한 줄로 읽는다
        a = lo + i
        if a % 4 == 0 and i + 4 <= len(before) and not any(inrun[i:i + 4]):
            row = {'off': i - WIN, 'addr': '0x%X' % a,
                   'rva': '0x%X' % (a - base) if a >= base else None,
                   'kind': 'num',
                   'hex': ' '.join('%02X' % x for x in before[i:i + 4]),
                   'u32': struct.unpack_from('<I', before, i)[0],
                   'u16': [struct.unpack_from('<H', before, i)[0],
                           struct.unpack_from('<H', before, i + 2)[0]]}
            f = struct.unpack_from('<f', before, i)[0]
            if f == f and abs(f) != float('inf') and 1e-6 < abs(f) < 1e9:
                row['f32'] = f
            if after != None:
                ch = {}
                for key, fmt, n in (('u32', '<I', 4), ('u16', '<H', 2)):
                    o = struct.unpack_from(fmt, before, i)[0]
                    v = struct.unpack_from(fmt, after, i)[0]
                    if o != v:
                        ch[key] = {'before': o, 'after': v, 'delta': v - o}
                if ch:
                    row['changed'] = ch
            out.append(row)
            i += 4
            continue

        #자투리 : 정렬 전이거나, 글자 구간 직전이거나, 끝부분.
        #예전엔 4바이트씩 건너뛰다가 글자 구간 한가운데로 들어가 문장 앞머리를 삼켰고,
        #정렬 안 맞는 바이트는 조용히 사라졌다. 바이트가 안 보이게 되는 일은 없어야 한다
        j = i + 1
        while j < len(before) and not inrun[j]:
            aj = lo + j
            if aj % 4 == 0 and j + 4 <= len(before) and not any(inrun[j:j + 4]):
                break
            j += 1
        out.append({'off': i - WIN, 'addr': '0x%X' % a,
                    'rva': '0x%X' % (a - base) if a >= base else None,
                    'kind': 'pad', 'len': j - i,
                    'hex': ' '.join('%02X' % x for x in before[i:j])})
        i = j
    return out


#이 자리가 '살아 있는 구조체' 인지 '채팅/UI 글자 버퍼' 인지 가린다.
#  글자 비율이 높으면 문장 안에 이름이 박힌 것이다 (채팅 광고 등)
#  이름 앞뒤가 NUL 로 끊겨 있으면 구조체의 이름 칸일 가능성이 높다
def classify(before, nameoff, namelen, runs):
    textbytes = sum(b - a for a, b in runs)
    ratio = textbytes * 1.0 / max(1, len(before))

    def isbreak(i):
        return i < 0 or i >= len(before) or before[i] < 0x20

    standalone = isbreak(nameoff - 1) and isbreak(nameoff + namelen)

    #이름을 품은 글자 구간의 길이. 이름보다 훨씬 길면 문장 안에 박힌 것이다
    #(창 전체 글자 비율보다 이게 직접적인 신호다 - 주변이 0 으로 비어 있어도 판정된다)
    host = 0
    for a, b in runs:
        if a <= nameoff < b:
            host = b - a
            break
    embedded = host > namelen + 2

    if embedded:
        verdict = ('채팅/UI 글자 버퍼로 보임 - 이름이 %d바이트짜리 문장 안에 박혀 있다'
                   % host)
        score = 3
    elif standalone and ratio < 0.5:
        verdict = '구조체의 이름 칸으로 보임 (앞뒤가 끊겨 있고 글자 비율 %d%%)' % (ratio * 100)
        score = 0
    elif standalone:
        verdict = '이름은 끊겨 있으나 주변이 글자투성이 (%d%%)' % (ratio * 100)
        score = 1
    else:
        verdict = '판단 애매 (글자 %d%%)' % (ratio * 100)
        score = 2
    return score, verdict, round(ratio, 3), standalone

#4바이트를 여러 방식으로 해석해 본다. 어떤 게 HP 인지는 사람이 보는 게 빠를 때가 많다
def _row(before, after, off, lo, base):
    a = lo + off
    r = {'off': off - WIN,                       #이름 기준 상대 위치
         'addr': '0x%X' % a,
         'rva':  '0x%X' % (a - base) if a >= base else None,
         'hex':  ' '.join('%02X' % x for x in before[off:off + 4])}

    def take(buf, fmt, n):
        if off + n > len(buf):
            return None
        v = struct.unpack_from(fmt, buf, off)[0]
        if isinstance(v, float):
            #json 은 inf/nan 을 못 쓴다
            return v if (v == v and abs(v) != float('inf')) else None
        return v

    for key, fmt, n in (('u32', '<I', 4), ('i32', '<i', 4),
                        ('u16', '<H', 2), ('i16', '<h', 2),
                        ('u8',  '<B', 1), ('f32', '<f', 4)):
        r[key] = take(before, fmt, n)

    #이 자리에서 시작하는 16바이트를 글자로 읽어본다 (옆에 붙은 이름/혈맹명 찾기용)
    chunk = bytes(before[off:off + 16])
    try:
        txt = chunk.decode('cp949', 'replace')
    except Exception:
        txt = ''
    r['text'] = ''.join(c if (c.isprintable() and c != '\ufffd') else '.' for c in txt)

    if after != None:
        changed = {}
        for key, fmt, n in (('u32', '<I', 4), ('u16', '<H', 2)):
            o = take(before, fmt, n)
            v = take(after, fmt, n)
            if o != None and v != None and o != v:
                changed[key] = {'before': o, 'after': v, 'delta': v - o}
        if changed:
            r['changed'] = changed
    return r


#이름이 잡힌 자리마다 주변을 통째로 떠서 json 으로 만든다
def builddump(m, name, hits, snaps, withafter, full=False, anchor=None):
    out = {'name': name,
           'pid': m.pid,
           'module_base': '0x%X' % m.base,
           'window': WIN,
           'how_to_read': [
               'hits 는 구조체일 가능성이 높은 순서로 정렬돼 있다. verdict 를 먼저 본다',
               '채팅/UI 글자 버퍼로 분류된 자리는 이름이 문장 안에 박힌 것이라 HP 가 없다',
               'segments 가 읽기용이다. 글자는 한 덩어리로, 숫자는 4바이트 한 줄로 묶었다',
               'off 는 이름이 시작하는 자리를 0 으로 본 상대 위치, rva 는 mem.json 의 base 에 넣을 값',
               'changed 가 붙은 줄이 맞았을 때 변한 값이다. changed_summary 에 모아뒀다'],
           'hits': []}

    enc_of  = dict(hits)
    rows_all = []
    for addr, (lo, before) in sorted(snaps.items()):
        after = mr.readmem(m.h, lo, len(before)) if withafter else None
        enc = enc_of.get(addr, 'cp949')
        if anchor != None:
            nlen = 2 if enc == 'u16' else 4
        else:
            try:
                nlen = len(name.encode(enc))
            except Exception:
                nlen = len(name) * 2
        runs = _textruns(before)
        if anchor != None:
            #앵커 모드는 글자 판정이 의미 없다. 변한 값이 많은 자리를 앞세운다
            score, verdict, ratio, standalone = 0, ('기준값 %d 주변' % anchor), 0.0, True
        else:
            score, verdict, ratio, standalone = classify(before, addr - lo, nlen, runs)

        segs = segments(before, after, lo, m.base, runs)

        dump = []
        for off in range(0, len(before), 16):
            chunk = before[off:off + 16]
            txt = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            dump.append('0x%X  %-47s  %s'
                        % (lo + off, ' '.join('%02X' % b for b in chunk), txt))

        h = {'index': 0,
             'name_addr': '0x%X' % addr,
             'name_rva': '0x%X' % (addr - m.base) if addr >= m.base else None,
             'encoding': enc_of.get(addr, ''),
             'verdict': verdict,
             'standalone': standalone,
             'text_ratio': ratio,
             'changed_count': sum(1 for r in segs if 'changed' in r),
             'segments': segs,
             'hexdump': dump}
        if full:
            h['fields'] = [_row(before, after, off, lo, m.base)
                           for off in range(0, len(before) - 3, 4)]
        rows_all.append((score, -h['changed_count'], addr, h))

    #구조체로 보이는 것부터, 같은 등급이면 변한 값이 많은 것부터
    rows_all.sort(key=lambda r: (r[0], r[1], r[2]))
    for i, (score, nc, addr, h) in enumerate(rows_all, start=1):
        h['index'] = i
        out['hits'].append(h)

    changed = []
    for h in out['hits']:
        for r in h['segments']:
            if 'changed' in r:
                changed.append({'hit': h['index'], 'verdict': h['verdict'],
                                'addr': r['addr'], 'rva': r['rva'], 'off': r['off'],
                                'changed': r['changed']})
    out['changed_summary'] = changed
    out['hit_summary'] = [{'index': h['index'], 'name_addr': h['name_addr'],
                           'verdict': h['verdict'], 'changed': h['changed_count']}
                          for h in out['hits']]
    return out


def savedump(data, path):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return True
    except Exception as e:
        say('덤프 저장 실패 : ' + str(e))
        return False


#=====================================================================

def run():
    line()
    say(' 캐릭터 이름으로 HP 찾기')
    line()
    say()
    say('mem.json : ' + mp.MEM_PATH)
    if not mp.MEM_FOUND:
        say('mem.json 이 없다. 같은 폴더에 있어야 한다')
        return

    anchor = None
    raw_anchor = arg('--anchor')
    if raw_anchor != None:
        try:
            anchor = int(raw_anchor, 0)
        except ValueError:
            say('--anchor 는 숫자여야 한다 : ' + raw_anchor)
            return

    name = arg('--name')
    if anchor == None:
        if not name:
            say()
            try:
                name = input('캐릭터 이름을 입력하세요 (또는 --anchor 최대HP) : ').strip()
            except Exception:
                name = ''
        if not name or len(name) < 2:
            say('이름이 너무 짧다. 두 글자 이상이어야 찾을 수 있다')
            return
        if len(name.encode('cp949', 'ignore')) <= 4:
            say('! 이름이 %d글자뿐이다. 채팅 문장 곳곳에 걸릴 수 있어 이름+NUL 로 먼저 찾는다' % len(name))
            say('  그래도 안 되면 최대 HP 를 기준으로 : python findme.py --anchor <최대HP>')
    else:
        name = str(anchor)
    say()

    hf.KEY_NEXT = arg('--key', hf.KEY_NEXT)
    hf.KEY_QUIT = arg('--quit', hf.KEY_QUIT)
    if not hf.checkkeys():
        return

    #--- 붙기 ---
    for i in (3, 2, 1):
        say('쓸 게임 창을 클릭해 맨 앞에 두세요... ' + str(i))
        time.sleep(1)
    pid = mr.frontpid()
    m   = mr.Mem(mp.MEM_PATH, say)
    if not m.attach(pid):
        m = mr.Mem(mp.MEM_PATH, say)
        if not m.attach():
            say('붙기 실패 : ' + str(m.err))
            return
    say()

    try:
        #--- 1. 기준점 찾기 (이름 또는 최대HP 값) ---
        line()
        if anchor != None:
            say(' 1단계 : 메모리에서 값 %d (최대 HP) 를 찾는다' % anchor)
        else:
            say(" 1단계 : 메모리에서 '" + name + "' 을 찾는다")
        line()
        say()
        if anchor != None:
            hits = scananchor(m, anchor)
            nul  = False
        else:
            hits, nul = scanname(m, name)
        if not hits:
            say()
            if anchor != None:
                say('값 %d 를 못 찾았다. 최대 HP 숫자가 맞는지 확인한다' % anchor)
            else:
                say('이름을 못 찾았다. 가능한 이유 :')
                say('  - 이름을 잘못 적었다 (게임에 보이는 것과 똑같이, 띄어쓰기까지)')
                say('  - 이 클라이언트는 이름을 다른 방식으로 저장한다')
                say('  - 캐릭터 선택 화면이라 아직 안 들어갔다 (게임에 접속한 상태여야 한다)')
                say('  -> 최대 HP 를 기준으로 : python findme.py --anchor <최대HP>')
            return
        say()
        say('찾음 : %d군데%s' % (len(hits), '  (이름+NUL 로 걸러짐)' if nul else ''))
        enc_count = {}
        for a, e in hits:
            enc_count[e] = enc_count.get(e, 0) + 1
        for e, c in enc_count.items():
            say('    %-12s %d군데' % (e, c))

        #어느 영역에 있는지 - 모듈 정적 데이터 vs 힙. 살아 있는 구조체는 보통 힙에 있다
        modend = m.base
        try:
            for mn, mb, ms in mr.modules(m.pid):
                if mb == m.base:
                    modend = mb + ms
                    break
        except Exception:
            pass
        inmod = sum(1 for a, e in hits if m.base <= a < modend)
        say('    모듈 정적 영역 %d군데 / 그 밖(힙 등) %d군데' % (inmod, len(hits) - inmod))
        say()

        #--- 2. 주변 기록 ---
        snaps = snapshot(m, hits)
        say('각 자리의 앞뒤 %d바이트를 기록했다 (%d곳)' % (WIN, len(snaps)))
        say()

        #--- 3. 맞기 ---
        withafter = '--dump-only' not in sys.argv
        if withafter:
            line()
            say(' 2단계 : 몹한테 맞아서 HP 를 줄이세요')
            line()
            if not hf.waitkey('   HP 가 줄어든 것을 확인하고 누르세요'):
                say('중단 - 지금까지 읽은 것만 덤프로 남긴다')
                withafter = False
            say()
        else:
            say('--dump-only : 맞는 단계를 건너뛰고 지금 값만 덤프한다')
            say()

        #--- 덤프는 무슨 일이 있어도 남긴다 ---
        #자동 판정이 실패했을 때가 바로 눈으로 봐야 하는 순간이다
        #덤프에 담을 자리를 고른다. 주소순으로 자르면 안 된다 -
        #모듈 정적 영역(채팅 로그)이 주소가 낮아서 힙의 진짜 구조체가 통째로 잘린 적이 있다.
        #먼저 전부 분류한 뒤 구조체로 보이는 것부터 담고, 채팅 버퍼는 기본으로 뺀다
        enc_of = dict(hits)
        graded = []
        chat   = 0
        for addr, (lo, before) in snaps.items():
            if anchor != None:
                graded.append((0, addr))
                continue
            try:
                nlen = len(name.encode(enc_of.get(addr, 'cp949')))
            except Exception:
                nlen = len(name) * 2
            runs = _textruns(before)
            score, verdict, ratio, standalone = classify(before, addr - lo, nlen, runs)
            if score >= 3 and '--keep-chat' not in sys.argv:
                chat += 1
                continue
            graded.append((score, addr))
        graded.sort()
        keep = dict((a, snaps[a]) for sc, a in graded[:MAX_DUMP])
        if chat:
            say('채팅/UI 글자 버퍼로 보이는 %d곳은 덤프에서 뺐다 (--keep-chat 으로 포함)' % chat)
        if len(graded) > MAX_DUMP:
            say('구조체로 보이는 순으로 %d곳만 담는다 (--max 로 변경, 전체 %d곳)'
                % (MAX_DUMP, len(graded)))
        if not keep and snaps:
            #전부 채팅이면 그래도 몇 개는 남겨서 볼 수 있게 한다
            keep = dict(list(sorted(snaps.items()))[:min(5, len(snaps))])
            say('남은 자리가 없어 채팅 자리 %d곳을 참고용으로 담는다' % len(keep))
        data = builddump(m, name, hits, keep, withafter,
                         full='--full' in sys.argv, anchor=anchor)
        if savedump(data, outpath):
            line()
            say(' 구조 덤프 저장 : ' + outpath)
            line()
            say()
            say('  자리 %d곳 x 앞뒤 %d바이트' % (len(keep), WIN))
            say('  바뀐 값 %d개 - json 의 changed_summary 를 먼저 보세요'
                % len(data['changed_summary']))
            say()
            say('  자리별 판정 (구조체일 가능성 높은 순) :')
            for hs in data['hit_summary'][:12]:
                say('    %2d. %-12s 변한값 %2d  %s'
                    % (hs['index'], hs['name_addr'], hs['changed'], hs['verdict']))
            if len(data['hit_summary']) > 12:
                say('    ... (전체 %d곳)' % len(data['hit_summary']))
            say()
            say('  보는 법 :')
            say('    hit_summary      자리별 판정. 채팅 버퍼로 분류된 건 건너뛴다')
            say('    segments         읽기용. 글자는 한 덩어리, 숫자는 4바이트 한 줄')
            say('    off / rva        이름 기준 상대 위치 / mem.json 의 base 에 넣을 값')
            say('    changed          맞았을 때 변한 값 (changed_summary 에 모아둠)')
            say('    --full 을 주면 4바이트마다 전부 해석한 fields 도 넣는다')
            say()
            if data['changed_summary']:
                say('  바뀐 값 미리보기 :')
                for c in data['changed_summary'][:10]:
                    for k, v in c['changed'].items():
                        say('    [%d번 자리] %s  off %+5d  %-3s %d -> %d (%+d)'
                            % (c['hit'], c['addr'], c['off'], k,
                               v['before'], v['after'], v['delta']))
                say()

        if not withafter:
            return

        cands = rank(diffs(m, snaps, hits))
        if anchor != None:
            #현재 HP 는 최대 HP 를 넘을 수 없다. 기준점 바로 옆(±64) 에 있어야 한다
            cands = [c for c in cands if c['old'] <= anchor and abs(c['dist']) <= 64]
            for c in cands:
                if c['maxaddr'] == None:
                    c['maxaddr'], c['maxval'], c['maxdist'] = c['name_at'], anchor, abs(c['dist'])
            cands = rank(cands)
        if not cands:
            say('HP 로 보이는 감소값을 자동으로는 못 찾았다.')
            say('위 덤프의 changed_summary 를 직접 보세요.')
            say('찾으면 그 rva 를 알려주시면 mem.json 에 넣어드립니다.')
            return

        say('줄어든 값 %d개 (좋아 보이는 순) :' % len(cands))
        say()
        say('  %-18s %-5s %-9s %-9s %-8s %-7s %s'
            % ('주소', '타입', '이전', '현재', '감소', '이름거리', '최대치 후보'))
        for c in cands[:12]:
            mxs = ('0x%X (%d, %+d바이트)'
                   % (c['maxaddr'], c['maxval'], c['maxaddr'] - c['addr'])
                   if c['maxaddr'] != None else '없음')
            say('  0x%-16X %-5s %-9d %-9d %-8d %+-7d %s'
                % (c['addr'], c['kind'], c['old'], c['new'],
                   c['delta'], c['dist'], mxs))
        say()
        best = cands[0]

        #--- 4. 저장 ---
        line()
        say(' 저장')
        line()
        say()
        say('HP     : 0x%X (%s, 지금 %d)' % (best['addr'], best['kind'], best['new']))
        if best['maxaddr'] != None:
            say('HP최대 : 0x%X (%s, %d)'
                % (best['maxaddr'], best['kind'], best['maxval']))
        else:
            say('HP최대 : 못 찾음 (hp 만 저장한다)')
        say()

        if not hf.writejson(mp.MEM_PATH, m.base, best['addr'], best['kind'],
                            best['maxaddr'], best['kind']):
            return
        say('mem.json 저장 완료')
        say('    "hp":     { "base": "0x%X", "offsets": [], "type": "%s" }'
            % (best['addr'] - m.base, best['kind']))
        if best['maxaddr'] != None:
            say('    "hp_max": { "base": "0x%X", "offsets": [], "type": "%s" }'
                % (best['maxaddr'] - m.base, best['kind']))

        #다른 후보로 바꿔 쓸 수 있게 남겨둔다
        try:
            with open(os.path.join(mr.appdir(), hf.CANDS_FILE),
                      'w', encoding='utf-8') as f:
                json.dump({'base': m.base,
                           'cands': [[c['addr'], c['new'], c['kind']]
                                     for c in cands[:12]]}, f)
        except Exception:
            pass

        #--- 5. 확인 ---
        hf.verify(m, [(c['addr'], c['new'], c['kind']) for c in cands[:6]],
                  best['addr'])

        say()
        line()
        say(' 끝났다')
        line()
        say()
        say('* 표시한 열이 HP 바와 같이 움직였으면 성공이다.')
        say('다른 열이 맞으면 그 번호로 다시 저장한다 : python hpfind.py --pick 2')
    finally:
        m.detach()


if __name__ == '__main__':
    try:
        if not mr.IS_WIN:
            say('이 도구는 Windows 에서만 된다 (지금 : ' + sys.platform + ')')
        else:
            run()
    except KeyboardInterrupt:
        say()
        say('중단')
    except Exception:
        import traceback
        say()
        say('예기치 못한 오류 :')
        say(traceback.format_exc())
    finally:
        mr.holdconsole()
