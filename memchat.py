#memchat.py
#
#채팅 입력칸의 글자를 메모리에 직접 써 넣는다. main.py 의 채팅버프가 쓴다.
#키로 한 글자씩 치는 방식은 한/영 상태에 따라 글자가 달라져서('.버프' 가 '.qjvm' 로 들어감)
#입력칸이 들고 있는 글자 버퍼를 바로 채운다. 채팅칸 열기 / 전송은 여전히 엔터 키다.
#
#채팅 입력칸 구조 (2026-11-15 실기, memprobe.py --chatfind 로 찾음) :
#   mem.json chains.chat_str 이 가리키는 곳에 '글자 묶음' 이 있다
#     +0  u32  글자 버퍼 포인터 (UTF-16LE)
#     +4  u32  글자 수            (".qjvm" 을 쳤을 때 5)
#     +8  u32  12 (뜻 모름. 글자가 없어 버퍼가 0 일 때도 12 라서 버퍼 크기는 아니다)
#   경로는 [[lin.exe + 0xA3288] + 0x28] + 0 을 쓴다 (게임을 껐다 켜도 그대로, 세 번 확인).
#   같이 나왔던 0x9BF98 은 '지금 입력 중인 칸' 포인터라 채팅칸에 글자가 없으면 0 이 된다.
#   글자가 한 자도 없으면 버퍼 포인터가 0 이다 (게임이 첫 글자를 받을 때 버퍼를 만든다).
#   버퍼가 얼마나 크게 잡히는지 모르므로, 밖에서 글자 수를 늘려 쓰지 않는다 :
#   '이미 들어 있는 글자 수 이하' 로만 덮어쓴다. 그래서 부르는 쪽(main.dochatbuff)이
#   한/영과 상관없는 숫자 키를 글자 수만큼 먼저 쳐서 자리를 만든 뒤 이 모듈로 덮어쓴다.
#
#쓰는 주소는 전부 mem.json 에 적힌 chains.chat_str 에서 나온다 (CLAUDE.md 규칙 2).
#되돌리기는 하지 않는다 - 전송하면 게임이 입력칸을 스스로 비운다.
#
#혼자 돌리기 (Windows. 게임에서 엔터로 채팅칸을 열어 둔 채로) :
#   python memchat.py               지금 입력칸의 글자와 길이/크기를 읽어 보여준다 (읽기만)
#   python memchat.py ".버프"       그 글자를 입력칸에 써 넣는다. 화면에 보이면 엔터로 전송해 본다
#
#같은 폴더에 memread.py, memcast.py (쓰기 함수를 빌려 쓴다) 가 있어야 한다

import struct
import sys

import memread as mr

CHAT_MAX = 64      #한 번에 쓰는 글자 수 상한 (버퍼 크기 칸이 이상하게 클 때의 안전장치)


class Chat(object):
    #mem = 붙어 있는 memread.Mem
    def __init__(self, mem):
        self.mem = mem
        self.hw  = None       #쓰기 핸들. 처음 쓸 때 연다
        self.err = None

    def close(self):
        if self.hw:
            mr.k32.CloseHandle(mr.wt.HANDLE(self.hw))
            self.hw = None

    #글자 묶음을 읽는다. (묶음 주소, 버퍼 주소, 글자 수, 버퍼 크기) 또는 None
    def info(self):
        m = self.mem
        spec = ((m.cfg or {}).get('chains') or {}).get('chat_str')
        if spec == None or spec.get('base') == None:
            self.err = 'mem.json chains.chat_str 가 없다'
            return None
        with m.lock:
            addr = m.resolve(spec)
            raw  = mr.readmem(m.h, addr, 12) if addr else None
        if raw == None:
            self.err = '채팅 입력칸을 못 읽었다 (경로가 틀렸거나 월드 밖)'
            return None
        buf, cnt, cap = struct.unpack('<III', raw)
        #글자가 없으면 버퍼가 0 이다 (정상). 글자가 있는데 버퍼가 주소가 아니면 경로가 틀린 것
        if cnt > CHAT_MAX * 4 or (cnt > 0 and buf < 0x10000) or (cnt == 0 and buf != 0 and buf < 0x10000):
            self.err = ('채팅 입력칸 값이 이상하다 (버퍼 0x%X, 글자 %d, +8 %d) - 경로가 틀린 듯'
                        % (buf, cnt, cap))
            return None
        return addr, buf, cnt, cap

    #지금 입력칸에 든 글자. 못 읽으면 None
    def text(self):
        got = self.info()
        if got == None:
            return None
        addr, buf, cnt, cap = got
        if cnt == 0:
            return ''
        raw = mr.readmem(self.mem.h, buf, cnt * 2)
        if raw == None:
            self.err = '글자 버퍼를 못 읽었다'
            return None
        return raw.decode('utf-16le', 'replace')

    #입력칸의 글자를 text 로 바꾼다. 성공하면 True
    #지금 들어 있는 글자 수보다 길면 쓰지 않는다 (버퍼가 얼마나 큰지 몰라서 밖에서 못 늘린다).
    #같은 길이면 글자만 덮어쓰고, 짧으면 글자 수 칸도 줄인다
    def put(self, text):
        import memcast                     #openwrite / writemem 을 빌려 쓴다
        got = self.info()
        if got == None:
            return False
        addr, buf, cnt, cap = got
        n = len(text)
        if n == 0 or n > CHAT_MAX:
            self.err = '글자 수가 이상하다 (%d)' % n
            return False
        if buf == 0 or cnt < n:
            self.err = ('입력칸에 든 글자(%d)가 써 넣을 글자(%d)보다 적다 - 먼저 그만큼 쳐 둬야 한다'
                        % (cnt, n))
            return False
        if self.hw == None:
            self.hw = memcast.openwrite(self.mem.pid)
            if self.hw == None:
                self.err = '쓰기 권한으로 프로세스를 못 열었다 (관리자 권한으로 실행)'
                return False
        #글자만 덮어쓴다. 끝의 0 은 이미 있던 자리(글자 수 cnt 뒤)를 넘지 않을 때만 쓴다
        data = text.encode('utf-16le')
        if n < cnt:
            data += b'\x00\x00'
        if not memcast.writemem(self.hw, buf, data):
            self.err = '글자 버퍼 쓰기 실패'
            return False
        if n < cnt and not memcast.writemem(self.hw, addr + 4, struct.pack('<I', n)):
            self.err = '글자 수 쓰기 실패'
            return False
        #다시 읽어 확인한다. 그 사이 게임이 버퍼를 바꿨으면 실패로 본다
        if self.text() != text:
            self.err = '써 넣은 글자가 다시 읽히지 않는다'
            return False
        self.err = None
        return True


#경로를 한 단계씩 따라가며 어디서 끊기는지 찍는다 (읽기만). 채팅칸 상태별 진단용
#chat_str 과 같은 오프셋으로, 같이 발견됐던 다른 시작 주소(0xA3288)도 함께 본다
CHAT_TRACE_BASES = ['0x9BF98', '0xA3288']

def trace(m):
    spec = ((m.cfg or {}).get('chains') or {}).get('chat_str') or {}
    offs = [mr.num(x, 0) for x in (spec.get('offsets') or [])]
    bases = []
    for b in [spec.get('base')] + CHAT_TRACE_BASES:
        v = mr.num(b)
        if v != None and v not in bases:
            bases.append(v)
    for rva in bases:
        line = '  [lin.exe+0x%X]' % rva
        raw  = mr.readmem(m.h, m.base + rva, 4)
        addr = struct.unpack('<I', raw)[0] if raw != None else None
        line += ' = ' + ('0x%X' % addr if addr != None else '못 읽음')
        for o in offs[:-1]:
            if not addr or addr < 0x10000:
                line += '   -> 여기서 끊김 (0 이거나 주소가 아님)'
                addr = None
                break
            raw  = mr.readmem(m.h, addr + o, 4)
            nxt  = struct.unpack('<I', raw)[0] if raw != None else None
            line += '   [+0x%X] = ' % o + ('0x%X' % nxt if nxt != None else '못 읽음')
            addr = nxt
        if addr and addr >= 0x10000 and len(offs) > 0:
            raw = mr.readmem(m.h, addr + offs[-1], 12)
            if raw != None:
                line += '   묶음 = 버퍼 0x%X, 글자 %d, 크기 %d' % struct.unpack('<III', raw)
            else:
                line += '   묶음 못 읽음'
        elif addr != None:
            line += '   -> 여기서 끊김 (0 이거나 주소가 아님)'
        print(line)


def main():
    if not mr.IS_WIN:
        print('Windows 에서만 된다')
        return
    path, okay, tried = mr.findfile('mem.json')
    m = mr.Mem(path, print)
    if not m.attach():
        print('붙기 실패 : ' + str(m.err))
        return
    c = Chat(m)
    try:
        print('경로 따라가기 :')
        trace(m)
        got = c.info()
        if got == None:
            print(c.err)
            return
        print('글자 묶음 0x%X   버퍼 0x%X   글자 수 %d   +8 값 %d' % got)
        print('지금 글자 : ' + repr(c.text()))
        args = [a for a in sys.argv[1:] if not a.startswith('--')]
        if len(args) == 0:
            print('써 넣으려면 : 채팅칸에 숫자를 글자 수만큼 쳐 두고 (".버프" 면 111)  python memchat.py ".버프"')
            return
        if c.put(args[0]):
            print('써 넣음 : ' + repr(args[0]) + '   게임 채팅칸에 보이는지 확인하고 엔터로 전송해 본다')
        else:
            print('실패 : ' + str(c.err))
    finally:
        c.close()
        m.detach()


if __name__ == '__main__':
    try:
        main()
    finally:
        mr.holdconsole()
