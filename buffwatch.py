#buffwatch.py - 내 캐릭터의 버프(상태효과)를 메모리에서 읽어 계속 보여 주는 도구
#
#  읽기 전용이다. 게임에 키/마우스 입력을 전혀 보내지 않고, 메모리에도 아무것도 쓰지 않는다.
#  memread.Mem.buffs() 가 읽은 버프 목록을 1초마다(또는 --sec 주기로) 콘솔에 다시 그린다.
#
#  쓰는 법 (Windows, 게임을 띄운 상태에서) :
#
#     python buffwatch.py                게임 창을 맨 앞에 두고 3초 뒤 그 창에 붙는다
#     python buffwatch.py --pid 1234     PID 를 직접 지정 (memprobe.py --list 로 확인)
#     python buffwatch.py --sec 0.5      다시 그리는 주기(초) 바꾸기
#     python buffwatch.py --once         한 번만 찍고 끝낸다
#
#  오프셋이 아직 안 맞아 이름이 안 뜨면, 먼저 아래로 원본 바이트를 보고 맞춘다 :
#     python memprobe.py --buffs
#  그걸로 확인한 값을 mem.json 의 buff 블록(icon_off/name_ptr_off/ptr_array 등)에 적는다.
#
#  Ctrl+C 로 멈춘다.

import os
import sys
import time

import memread as mr

MEM_PATH = os.path.join(mr.appdir(), 'mem.json')


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def has(name):
    return name in sys.argv


def pickpid():
    raw = arg('--pid')
    if raw != None:
        try:
            return int(raw)
        except ValueError:
            print('--pid 는 숫자여야 한다 : ' + str(raw))
            sys.exit(1)
    #--pid 가 없으면 맨 앞 창에 붙게 둔다 (attach 가 알아서 고른다). 3초 준다
    print('쓸 게임 창을 맨 앞에 둬라. 3초 뒤 맨 앞 창에 붙는다...')
    time.sleep(3)
    return None


def draw(buffs, win, count):
    #화면을 지우고 다시 그린다 (watch 처럼)
    os.system('cls' if os.name == 'nt' else 'clear')
    print('=== 버프(상태효과) 감시  -  읽기 전용 ===')
    if win == None:
        print('버프 바를 못 읽었다. 캐릭터로 월드에 들어간 뒤 다시 돌린다 (mem.json chains.buff_win 확인)')
        return
    print('버프 바 위젯 0x%X   칸 %s개   읽은 버프 %d개' % (win, str(count), len(buffs)))
    print('-' * 56)
    if len(buffs) == 0:
        print('(켠 버프가 없거나 오프셋이 아직 안 맞는다 - python memprobe.py --buffs 로 맞춘다)')
        return
    for b in buffs:
        sec = '' if b.get('sec') == None else ('   남은 %ds' % b['sec'])
        name = b['name'] if b['name'] != None else '(이름 못 읽음)'
        print('  아이콘 %-5d  %s%s' % (b['icon'], name, sec))


def main():
    m = mr.Mem(MEM_PATH, print)
    pid = pickpid()
    if not m.attach(pid):
        print('붙기 실패 : ' + str(m.err))
        return
    try:
        sec = float(arg('--sec', '1'))
    except ValueError:
        sec = 1.0
    sec = max(0.2, sec)
    try:
        while True:
            buffs, win, count = m.buffs()
            draw(buffs, win, count)
            if has('--once'):
                break
            time.sleep(sec)
    except KeyboardInterrupt:
        pass
    finally:
        m.detach()


if __name__ == '__main__':
    main()
