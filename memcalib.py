#월드 좌표 -> 화면 좌표 변환을 실측해서 mem.json 에 넣는다
#
#  타일 크기를 추측해서 코드에 박지 않는다. 해상도/줌/UI 가 바뀌면 이 도구만 다시 돌린다
#
#쓰는 법 (Windows, 게임을 띄우고 몹이 여러 마리 보이는 자리에서) :
#
#   python memcalib.py
#
#   1) 몹 하나에 마우스를 올린다 (커서가 공격 모양으로 바뀌는 자리)
#   2) insert 키를 누른다  -> 그 순간의 커서 위치와 몹 목록을 같이 기록한다
#   3) 다른 몹으로 1~2 를 5번 이상 반복한다. 가능하면 멀리 떨어진 몹들로 섞는다
#   4) end 키를 누르면 계산한다
#   5) 계산한 변환으로 실제 몹 위치를 찍어보고(커서 모양 확인) 맞으면 mem.json 에 저장한다
#
#   python memcalib.py --key f1      기록 키 바꾸기
#   python memcalib.py --show        지금 저장된 변환으로 몹 위치를 찍어만 본다
#   python memcalib.py --noverify    5번 검증을 건너뛴다 (권하지 않음)
#   python memcalib.py --fg          게임 창을 맨 앞에 두고 3초 뒤 그 창에 붙는다 (듀얼클라)
#   python memcalib.py --pid 1234    붙을 프로세스를 직접 지정 (듀얼클라)
#
#어떻게 푸는가 :
#  커서를 올린 순간 "어느 몹인지" 는 알 수 없다. 그래서 표본마다 몹 전체를 후보로 두고,
#  표본 2개 + 후보 조합으로 변환을 가정해본 뒤 나머지 표본이 몇 개나 들어맞는지 센다
#  (RANSAC). 가장 많이 들어맞은 가정을 골라 그 대응들로 최소제곱 보정한다
#
#  통계만으로는 '우연히 들어맞은 엉터리 변환' 을 완전히 걸러낼 수 없다. 그래서 마지막에
#  게임 자체를 정답지로 쓴다 : 구한 변환으로 몹이 있어야 할 자리에 커서를 올려보고
#  게임이 커서 모양을 공격 커서로 바꿔주는지 센다. 이게 어떤 통계 문턱보다 확실하다
#
#게임에 보내는 입력 : 커서 이동만. 클릭도 키 입력도 하지 않는다
import json
import os
import sys
import time

import memread as mr

#exe 로 묶었을 때도 exe 옆의 mem.json 을 쓴다 (__file__ 은 임시 폴더를 가리킨다)
CAL_PATH, CAL_FOUND, CAL_TRIED = mr.findfile('mem.json')

TOL      = 28       #이 픽셀 안에 들어오면 '들어맞았다' 로 본다
MIN_PICK = 4        #최소 표본 수
MAX_MOB  = 24       #표본 하나에서 후보로 둘 몹 수 (가까운 순)

#아래 세 개는 '엉터리 변환을 저장하지 않기' 위한 문턱이다.
#표본 하나마다 몹 수십 마리를 후보로 두므로, 좌표가 전부 엉망이어도 우연히 몇 개는
#들어맞는 변환이 나온다. 실측이 제대로 됐으면 거의 모든 표본이 들어맞아야 정상이다
INLIER_RATIO = 0.8   #표본 중 이 비율 이상이 들어맞아야 받아들인다
ERR_MAX      = TOL / 2.0   #평균 오차가 이보다 크면 버린다
DET_MIN      = 4.0   #행렬식이 이보다 작으면 찌그러진 변환이다
ELEM_MAX     = 400.0 #한 칸 크기가 이보다 크면 말이 안 된다

#실측 검증 : 구한 변환으로 몹 자리를 찍어보고 커서가 공격 모양이 되는 비율
#UI 에 가린 몹, 벽 뒤 몹이 있으므로 100% 는 안 나온다. 6할이면 변환이 맞은 것이다
VERIFY_N    = 12     #최대 몇 마리를 찍어볼지
VERIFY_PASS = 0.6    #이 비율 이상이 공격 커서가 되어야 통과


def say(s=''):
    print(s)
    sys.stdout.flush()


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def has(name):
    return name in sys.argv


#--pid <N> / --fg 를 실제 PID 로 바꾼다. 둘 다 없으면 None (= attach 가 알아서 고른다)
#듀얼클라에서는 "표본을 찍을 그 창" 에 붙어야 하므로 이게 중요하다
def pickpid():
    raw = arg('--pid')
    if raw != None:
        try:
            return int(raw)
        except ValueError:
            say('--pid 는 숫자여야 한다 : ' + str(raw))
            return -1
    if has('--fg'):
        for i in (3, 2, 1):
            say('표본을 찍을 게임 창을 클릭해 맨 앞에 두세요... ' + str(i))
            time.sleep(1)
        pid = mr.frontpid()
        if pid == None:
            say('맨 앞 창을 못 찾았다')
            return -1
        t = mr.windows(pid).get(pid, [])
        say('맨 앞 창 : PID ' + str(pid) + '  ' + (' | '.join(t) if t else '(제목 없음)'))
        return pid
    return None


#=====================================================================
# 3x3 최소제곱 (numpy 없이)
#=====================================================================

#sx = a*dx + b*dy + c 를 최소제곱으로 푼다. pairs = [(dx, dy, sx), ...]
#정규방정식 3x3 을 가우스 소거로 푼다. 못 풀면 None
def _fit3(pairs):
    A = [[0.0] * 3 for _ in range(3)]
    B = [0.0] * 3
    for dx, dy, s in pairs:
        row = (float(dx), float(dy), 1.0)
        for i in range(3):
            for j in range(3):
                A[i][j] += row[i] * row[j]
            B[i] += row[i] * float(s)

    #가우스 소거 (부분 피벗)
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(A[r][col]))
        if abs(A[piv][col]) < 1e-9:
            return None
        if piv != col:
            A[col], A[piv] = A[piv], A[col]
            B[col], B[piv] = B[piv], B[col]
        for r in range(col + 1, 3):
            f = A[r][col] / A[col][col]
            if f == 0.0:
                continue
            for c in range(col, 3):
                A[r][c] -= f * A[col][c]
            B[r] -= f * B[col]

    out = [0.0] * 3
    for r in (2, 1, 0):
        acc = B[r]
        for c in range(r + 1, 3):
            acc -= A[r][c] * out[c]
        out[r] = acc / A[r][r]
    return out


#2x2 연립 : [p, q] = M . [dx, dy] 두 쌍으로 M 한 줄을 구한다
#  s1 = a*dx1 + b*dy1 ,  s2 = a*dx2 + b*dy2
def _solve2(dx1, dy1, s1, dx2, dy2, s2):
    det = dx1 * dy2 - dy1 * dx2
    if abs(det) < 1e-9:
        return None
    a = (s1 * dy2 - dy1 * s2) / det
    b = (dx1 * s2 - s1 * dx2) / det
    return a, b


#=====================================================================
# 변환 적용 / 평가
#=====================================================================

#찌그러졌거나 크기가 말이 안 되는 변환을 걸러낸다
#우연히 몇 점이 들어맞는 쓰레기 가정은 대개 여기서 죽는다
def sanem(m):
    det = m[0][0] * m[1][1] - m[0][1] * m[1][0]
    if abs(det) < DET_MIN:
        return False
    for row in m:
        for v in row:
            if abs(v) > ELEM_MAX:
                return False
    return True


def apply(m, og, dx, dy):
    return (og[0] + m[0][0] * dx + m[0][1] * dy,
            og[1] + m[1][0] * dx + m[1][1] * dy)


#표본 하나가 이 변환으로 설명되는지. 되면 (오차, 맞은몹) 아니면 None
def _inlier(m, og, sample, tol):
    best = None
    for o in sample['mobs']:
        px, py = apply(m, og, o['dx'], o['dy'])
        err = ((px - sample['sx']) ** 2 + (py - sample['sy']) ** 2) ** 0.5
        if err <= tol and (best == None or err < best[0]):
            best = (err, o)
    return best


#RANSAC. samples = [{'sx','sy','mobs':[{'dx','dy','id','name'}]}]
#돌려주는 것 : (m, origin, 맞은표본수, 평균오차) 또는 None
def solve(samples, origin, tol):
    n = len(samples)
    if n < 2:
        return None

    best = None
    for i in range(n):
        for j in range(i + 1, n):
            si, sj = samples[i], samples[j]
            for a in si['mobs']:
                for b in sj['mobs']:
                    #원점을 캐릭터 자리로 고정하고 M 2x2 만 가정한다
                    rx = _solve2(a['dx'], a['dy'], si['sx'] - origin[0],
                                 b['dx'], b['dy'], sj['sx'] - origin[0])
                    ry = _solve2(a['dx'], a['dy'], si['sy'] - origin[1],
                                 b['dx'], b['dy'], sj['sy'] - origin[1])
                    if rx == None or ry == None:
                        continue
                    m = [[rx[0], rx[1]], [ry[0], ry[1]]]
                    if not sanem(m):
                        continue

                    hits = []
                    for s in samples:
                        got = _inlier(m, origin, s, tol)
                        if got != None:
                            hits.append((s, got[1], got[0]))
                    if len(hits) < 2:
                        continue
                    score = (len(hits), -sum(h[2] for h in hits) / len(hits))
                    if best == None or score > best[0]:
                        best = (score, m, hits)

    if best == None:
        return None

    #--- 들어맞은 대응들로 원점까지 같이 최소제곱 보정 ---
    hits = best[2]
    px = [(h[1]['dx'], h[1]['dy'], h[0]['sx']) for h in hits]
    py = [(h[1]['dx'], h[1]['dy'], h[0]['sy']) for h in hits]
    fx = _fit3(px) if len(px) >= 3 else None
    fy = _fit3(py) if len(py) >= 3 else None

    if fx != None and fy != None:
        m  = [[fx[0], fx[1]], [fy[0], fy[1]]]
        og = [fx[2], fy[2]]
    else:
        m  = best[1]
        og = [float(origin[0]), float(origin[1])]

    if not sanem(m):
        return None

    errs = []
    for h in hits:
        qx, qy = apply(m, og, h[1]['dx'], h[1]['dy'])
        errs.append(((qx - h[0]['sx']) ** 2 + (qy - h[0]['sy']) ** 2) ** 0.5)
    avg = sum(errs) / len(errs) if errs else 0.0
    return m, og, len(hits), avg


#=====================================================================
# 표본 수집
#=====================================================================

#표본을 모으면서 '공격 커서 핸들' 도 같이 얻는다
#사용자가 몹에 커서를 올린 순간이 바로 공격 커서인 순간이므로, main.setattckinfo 처럼
#게임을 클릭해서 캘리브레이션할 필요가 없다 (입력을 아예 안 보낸다)
#돌려주는 것 : (표본목록, 공격커서핸들 or None)
def collect(m, keyname, origin):
    import keyboard as k
    import win32api
    import win32gui

    samples = []
    curs    = {}
    say()
    say('몹에 마우스를 올리고 [' + keyname + '] 를 누르세요. 끝내려면 [end]')
    say('  - 서로 멀리 떨어진 몹들로 5개 이상 모으면 정확해집니다')
    say('  - 게임에 클릭이나 키를 보내지 않습니다 (커서 위치만 읽습니다)')
    say()

    down = False
    while True:
        if k.is_pressed('end'):
            break

        hot = k.is_pressed(keyname)
        if hot and not down:
            down = True

            sx, sy = win32api.GetCursorPos()
            cur    = win32gui.GetCursorInfo()[1]
            me     = m.selfpos()
            if me == None:
                say('  ! 내 좌표를 못 읽었다. chains.self_x / self_y 를 확인하세요')
                continue
            mobs = m.mobs()
            if len(mobs) == 0:
                say('  ! 몹 목록이 비었다. objlist 설정을 확인하세요')
                continue

            rows = []
            for o in mobs:
                x, y = o.get('x'), o.get('y')
                if not isinstance(x, int) or not isinstance(y, int):
                    continue
                rows.append({'dx': x - me[0], 'dy': y - me[1],
                             'id': o.get('id'), 'name': o.get('name', '')})
            rows.sort(key=lambda r: r['dx'] ** 2 + r['dy'] ** 2)
            rows = rows[:MAX_MOB]
            if len(rows) == 0:
                say('  ! 좌표를 읽을 수 있는 몹이 없다')
                continue

            samples.append({'sx': sx, 'sy': sy, 'mobs': rows})
            curs[cur] = curs.get(cur, 0) + 1
            say('  %d번 기록 : 커서 (%d, %d)  내좌표 (%d, %d)  후보 몹 %d마리  커서핸들 %s'
                % (len(samples), sx, sy, me[0], me[1], len(rows), cur))
        elif not hot:
            down = False

        time.sleep(0.03)

    #표본마다 핸들이 같아야 정상이다. 제일 많이 나온 걸 공격 커서로 본다
    atk = None
    if len(curs) > 0:
        atk = max(curs.items(), key=lambda kv: kv[1])[0]
        if len(curs) > 1:
            say()
            say('  ! 커서 핸들이 ' + str(len(curs)) + '종류 나왔다 : ' + str(curs))
            say('    몹이 아닌 자리에서 누른 표본이 섞였을 수 있다. 가장 많이 나온 '
                + str(atk) + ' 를 공격 커서로 본다')
    return samples, atk


#=====================================================================
# 실측 검증 : 게임에게 직접 물어본다
#=====================================================================

#구한 변환으로 몹이 있어야 할 자리에 커서를 올려보고, 게임이 공격 커서로 바꿔주는지 센다
#클릭하지 않는다. 커서만 움직인다. 돌려주는 것 : (맞은수, 시도수)
def verify(m, mat, og, atk):
    import main

    me = m.selfpos()
    if me == None:
        return 0, 0

    #파크 자리는 main.huntloop 과 같은 계산을 쓴다 (사냥 영역 아래)
    cx = main.CENTERPOINT[0]
    cy = main.CENTERPOINT[1] + main.SCAN_OFFSET_Y
    park = (cx, cy + main.SCAN_START * main.SCAN_FAR + main.PARK_GAP)

    rows = []
    for o in m.mobs():
        x, y = o.get('x'), o.get('y')
        if not isinstance(x, int) or not isinstance(y, int):
            continue
        rows.append((((x - me[0]) ** 2 + (y - me[1]) ** 2), o))
    rows.sort(key=lambda r: r[0])

    hit = 0
    n   = 0
    for d, o in rows[:VERIFY_N]:
        sp = apply(mat, og, o.get('x') - me[0], o.get('y') - me[1])
        sx, sy = int(round(sp[0])), int(round(sp[1]))
        main._movefast(park[0], park[1])          #커서 초기화 (안 하면 모양이 안 갱신된다)
        time.sleep(main.PROBE_SETTLE)
        n += 1
        if main._probe(sx, sy, atk):
            hit += 1
            mark = 'O'
        else:
            mark = 'X'
        say('    %s  id %-8s 월드 %s,%s -> 화면 %d,%d  %s'
            % (mark, str(o.get('id')), o.get('x'), o.get('y'), sx, sy,
               str(o.get('name', ''))))
    return hit, n


#=====================================================================
# 저장 / 표시
#=====================================================================

#mem.json 의 screen 만 갈아끼운다. 나머지 키와 순서, 주석(_ 키)은 그대로 둔다
def store(m, og):
    try:
        f = open(CAL_PATH, 'r', encoding='utf-8')
        data = json.load(f)
        f.close()
    except Exception as e:
        say('mem.json 읽기 실패 : ' + str(e))
        return False

    data['screen'] = {'m': [[round(m[0][0], 6), round(m[0][1], 6)],
                            [round(m[1][0], 6), round(m[1][1], 6)]],
                      'origin': [round(og[0], 2), round(og[1], 2)]}
    try:
        f = open(CAL_PATH, 'w', encoding='utf-8')
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.close()
    except Exception as e:
        say('mem.json 저장 실패 : ' + str(e))
        return False
    return True


#지금 저장된 변환으로 몹들이 화면 어디로 가는지 찍어본다
def show(m):
    sc = m.cfg.get('screen')
    if sc == None:
        say('mem.json 에 screen 이 없다. 먼저 python memcalib.py 로 맞춘다')
        return
    me = m.selfpos()
    if me == None:
        say('내 좌표를 못 읽었다')
        return
    mobs = m.mobs()
    say('내 좌표 ' + str(me) + ' / 몹 ' + str(len(mobs)) + '마리')
    say()
    say('  %-10s %-14s %-14s %s' % ('id', '월드', '화면', '이름'))
    for o in sorted(mobs, key=lambda o: (o.get('x', 0) - me[0]) ** 2
                                        + (o.get('y', 0) - me[1]) ** 2)[:20]:
        sp = m.toscreen(o.get('x'), o.get('y'))
        say('  %-10s %-14s %-14s %s'
            % (str(o.get('id')),
               '%s,%s' % (o.get('x'), o.get('y')),
               ('%d,%d' % sp) if sp else '--',
               str(o.get('name', ''))))


#=====================================================================

def main_():
    if not mr.IS_WIN:
        say('이 도구는 Windows 에서만 된다 (지금 : ' + sys.platform + ')')
        return

    pid = pickpid()
    if pid == -1:
        return

    if CAL_FOUND:
        say('mem.json : ' + CAL_PATH)
    else:
        say('mem.json 을 못 찾았다. 찾아본 곳 :')
        for t in CAL_TRIED:
            say('    ' + t)
        return
    say()

    m = mr.Mem(CAL_PATH, say)
    if not m.attach(pid):
        say('메모리 붙기 실패 : ' + str(m.err))
        say('먼저 python memprobe.py 로 읽기가 되는지 확인한다')
        return

    try:
        if m.selfpos() == None:
            say('내 좌표(self_x / self_y)를 못 읽는다. mem.json 의 chains 를 먼저 채운다')
            return
        if len(m.mobs()) == 0:
            say('몹 목록이 비었다. mem.json 의 objlist 와 mob_types 를 먼저 채운다')
            say('  python memprobe.py --objs 로 확인')
            return

        if has('--show'):
            show(m)
            return

        #캐릭터는 항상 화면 중앙에 있다는 전제로 원점을 잡고 시작한다 (main.CENTERPOINT)
        #최종 원점은 최소제곱으로 다시 구하므로 여기 값은 시작점일 뿐이다
        try:
            import main
            origin = (main.CENTERPOINT[0], main.CENTERPOINT[1])
        except Exception:
            origin = (720, 540)
        say('시작 원점(캐릭터 화면 위치) : ' + str(origin))

        keyname      = arg('--key', 'insert')
        samples, atk = collect(m, keyname, origin)

        say()
        if len(samples) < MIN_PICK:
            say('표본이 ' + str(len(samples)) + '개뿐이다. ' + str(MIN_PICK)
                + '개 이상 모아야 한다')
            return

        say('표본 ' + str(len(samples)) + '개로 변환을 찾는다...')
        got = solve(samples, origin, TOL)
        if got == None:
            say('변환을 못 찾았다. 가능한 원인 :')
            say('  - 커서를 올린 몹이 목록에 없다 (objlist/mob_types 가 틀림)')
            say('  - x/y 필드 오프셋이 틀렸다')
            say('  - 표본이 한자리에 몰려 있다 (멀리 떨어진 몹들로 다시)')
            return

        mat, og, hits, avg = got
        say()
        say('결과 : 표본 ' + str(hits) + '/' + str(len(samples)) + '개가 들어맞음, '
            + '평균 오차 %.1fpx' % avg)
        say('  m      = [[%.4f, %.4f], [%.4f, %.4f]]'
            % (mat[0][0], mat[0][1], mat[1][0], mat[1][1]))
        say('  origin = [%.1f, %.1f]' % (og[0], og[1]))
        say()

        #표본 대부분이 들어맞아야 받아들인다. 일부만 맞는 건 우연히 나온 변환이다
        need = max(MIN_PICK, int(round(len(samples) * INLIER_RATIO)))
        if hits < need:
            say('들어맞은 표본이 ' + str(hits) + '/' + str(len(samples))
                + ' 뿐이다 (' + str(need) + '개 이상 필요). 저장하지 않는다')
            say('  좌표 오프셋이 틀렸거나, 커서를 올린 몹이 목록에 없을 수 있다')
            say('  python memprobe.py --objs 로 몹 목록부터 확인하세요')
            return
        if avg > ERR_MAX:
            say('평균 오차가 %.1fpx 로 너무 크다 (%.0fpx 이하여야 한다). 저장하지 않는다'
                % (avg, ERR_MAX))
            return

        #--- 실측 검증 : 통계가 아니라 게임에게 직접 물어본다 ---
        if has('--noverify'):
            say('검증 건너뜀 (--noverify). 저장만 한다 - 실제로 맞는지는 모른다')
        elif atk == None:
            say('공격 커서 핸들을 못 얻어 검증을 못 한다. 저장하지 않는다')
            say('  (표본을 기록할 때 커서가 몹 위에 있어야 한다)')
            return
        else:
            say('구한 변환으로 몹 자리를 실제로 찍어본다 (클릭은 안 한다, 커서만 이동)')
            say('공격 커서 핸들 : ' + str(atk))
            say()
            hit, n = verify(m, mat, og, atk)
            say()
            if n == 0:
                say('찍어볼 몹이 없다. 저장하지 않는다')
                return
            rate = hit * 1.0 / n
            say('검증 결과 : %d/%d 가 공격 커서가 됐다 (%.0f%%)' % (hit, n, rate * 100))
            if rate < VERIFY_PASS:
                say('기준(%.0f%%) 미달 - 변환이 틀렸다. 저장하지 않는다' % (VERIFY_PASS * 100))
                say('  다시 측정할 때 : 서로 멀리 떨어진 몹들로, 몹 몸통 가운데를 가리키세요')
                say('  계속 실패하면 objlist 의 x/y 오프셋이나 mob_types 가 틀린 것이다')
                return
            say('통과. 변환이 실제 화면과 맞는다')

        if store(mat, og):
            say('mem.json 의 screen 에 저장했다')
            say()
            say('확인 : python memcalib.py --show   (몹들의 화면 좌표가 실제 위치와 맞는지)')
            say('그 다음 pit.py 에서 [메모리에서 상태 읽기] + [몹 목록으로 타겟 집기] 를 켠다')
    finally:
        m.detach()


if __name__ == '__main__':
    #더블클릭으로 띄우면 콘솔이 바로 닫혀서 출력을 못 읽는다. 어떤 경우든 엔터를 기다린다
    try:
        main_()
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
