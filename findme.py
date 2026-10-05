#캐릭터 이름으로 캐릭터 구조체를 찾아 HP 를 짚어낸다
#
#  쓰는 법 :   python findme.py --name 캐릭터이름
#              python findme.py              (이름을 물어본다)
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
def scanname(m, name):
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
        return []

    say('찾는 바이트 :')
    for b, enc, label in needles:
        say('    %-10s %s' % (label, ' '.join('%02X' % x for x in b)))
    say()

    #이름은 쓰기 가능한 영역(살아 있는 구조체)에 있을 수도, 읽기 전용에 있을 수도 있다.
    #먼저 쓰기 가능한 쪽만 본다 - 우리가 원하는 건 값이 변하는 '살아 있는' 구조체다
    for writable in (True, False):
        regs  = mr.regions(m.h, writable=writable,
                           maxaddr=(1 << 32) if m.ptrsz == 4 else None)
        total = sum(r[1] for r in regs)
        say('검색 영역 %d개, %.1f MB  (%s)'
            % (len(regs), total / 1048576.0,
               '쓰기 가능' if writable else '읽기 전용 포함'))

        hits = []
        for base, size in regs:
            for at, raw in mr.readchunks(m.h, base, size):
                for b, enc, label in needles:
                    pos = raw.find(b)
                    while pos >= 0:
                        hits.append((at + pos, enc))
                        if len(hits) >= MAX_HITS:
                            break
                        pos = raw.find(b, pos + 1)
                if len(hits) >= MAX_HITS:
                    break
            if len(hits) >= MAX_HITS:
                break

        if hits:
            return hits
        say('  여기서는 못 찾았다')
    return []


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
def builddump(m, name, hits, snaps, withafter):
    out = {'name': name,
           'pid': m.pid,
           'module_base': '0x%X' % m.base,
           'window': WIN,
           'note': ('off 는 이름이 시작하는 자리를 0 으로 본 상대 위치다. '
                    'rva 를 mem.json 의 base 에 그대로 넣으면 된다. '
                    'changed 가 있는 줄이 맞았을 때 변한 값이다'),
           'hits': []}

    enc_of = dict(hits)
    for i, (addr, (lo, before)) in enumerate(sorted(snaps.items()), start=1):
        after = mr.readmem(m.h, lo, len(before)) if withafter else None
        rows  = []
        for off in range(0, len(before) - 3, 4):
            rows.append(_row(before, after, off, lo, m.base))

        dump = []
        for off in range(0, len(before), 16):
            chunk = before[off:off + 16]
            txt = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            dump.append('0x%X  %-47s  %s'
                        % (lo + off, ' '.join('%02X' % b for b in chunk), txt))

        out['hits'].append({
            'index': i,
            'name_addr': '0x%X' % addr,
            'name_rva': '0x%X' % (addr - m.base) if addr >= m.base else None,
            'encoding': enc_of.get(addr, ''),
            'region_start': '0x%X' % lo,
            'hexdump': dump,
            'fields': rows})

    #바뀐 것만 따로 모아 맨 위에 둔다. 제일 먼저 볼 곳이다
    changed = []
    for h in out['hits']:
        for r in h['fields']:
            if 'changed' in r:
                changed.append({'hit': h['index'], 'addr': r['addr'],
                                'rva': r['rva'], 'off': r['off'],
                                'changed': r['changed'], 'text': r['text']})
    out['changed_summary'] = changed
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

    name = arg('--name')
    if not name:
        say()
        try:
            name = input('캐릭터 이름을 입력하세요 : ').strip()
        except Exception:
            name = ''
    if not name or len(name) < 2:
        say('이름이 너무 짧다. 두 글자 이상이어야 찾을 수 있다')
        return
    say()

    global WIN, MAX_DUMP
    try:
        WIN = max(32, min(4096, int(arg('--win', WIN))))
        MAX_DUMP = max(1, int(arg('--max', MAX_DUMP)))
    except ValueError:
        say('--win / --max 는 숫자여야 한다')
        return
    outpath = arg('--out', os.path.join(mr.appdir(), DUMP_NAME))

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
        #--- 1. 이름 찾기 ---
        line()
        say(" 1단계 : 메모리에서 '" + name + "' 을 찾는다")
        line()
        say()
        hits = scanname(m, name)
        if not hits:
            say()
            say('이름을 못 찾았다. 가능한 이유 :')
            say('  - 이름을 잘못 적었다 (게임에 보이는 것과 똑같이, 띄어쓰기까지)')
            say('  - 이 클라이언트는 이름을 다른 방식으로 저장한다')
            say('  - 캐릭터 선택 화면이라 아직 안 들어갔다 (게임에 접속한 상태여야 한다)')
            return
        say()
        say('찾음 : %d군데' % len(hits))
        enc_count = {}
        for a, e in hits:
            enc_count[e] = enc_count.get(e, 0) + 1
        for e, c in enc_count.items():
            say('    %-12s %d군데' % (e, c))
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
        keep = dict(list(sorted(snaps.items()))[:MAX_DUMP])
        if len(snaps) > MAX_DUMP:
            say('덤프는 앞 %d곳만 담는다 (--max 로 변경)' % MAX_DUMP)
        data = builddump(m, name, hits, keep, withafter)
        if savedump(data, outpath):
            line()
            say(' 구조 덤프 저장 : ' + outpath)
            line()
            say()
            say('  자리 %d곳 x 앞뒤 %d바이트' % (len(keep), WIN))
            say('  바뀐 값 %d개 - json 의 changed_summary 를 먼저 보세요'
                % len(data['changed_summary']))
            say()
            say('  보는 법 :')
            say('    off     이름이 시작하는 자리를 0 으로 본 상대 위치')
            say('    rva     mem.json 의 base 에 그대로 넣을 값')
            say('    u32/u16/f32  그 자리를 각 타입으로 읽은 값')
            say('    text    그 자리부터 16바이트를 글자로 (옆 이름/혈맹명 찾기)')
            say('    changed 맞았을 때 변한 값 - 여기에 HP 가 있을 가능성이 높다')
            say('    hexdump 사람이 읽기 좋은 16진 덤프')
            say()
            if data['changed_summary']:
                say('  바뀐 값 미리보기 :')
                for c in data['changed_summary'][:10]:
                    for k, v in c['changed'].items():
                        say('    %s  off %+5d  %-3s %d -> %d (%+d)'
                            % (c['addr'], c['off'], k,
                               v['before'], v['after'], v['delta']))
                say()

        if not withafter:
            return

        cands = rank(diffs(m, snaps, hits))
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
