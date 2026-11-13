# diag_findself.py
#
# self 구조체(플레이어 구조체)를 메모리에서 찾는 진단 스크립트.
# 읽기만 한다. 게임 메모리를 바꾸지 않는다.
#
# 배경: diag_selfptr.py 결과, DAT_005ab548(0x5AB548)은 포인터 변수인데
# 런타임에 값이 0이고, 주변 바이트도 self 구조체가 아니다.
# (H1/H2 둘 다 아님.) Ghidra 의사코드로 DAT_005ab548이 포인터인 건 맞는데,
# 아마 스킬을 쓸 때만 세팅되는 일시적인 포인터이거나 주소가 틀렸다.
# 그래서 self 구조체를 메모리 스캔으로 직접 찾는다.
#
# 찾는 패턴 (엔티티 테이블의 self 값과 대조):
#   구조체 베이스 P에 대해 [P+0x04] == self id, [P+0x28] == x_raw, [P+0x2C] == y_raw
# 엔티티 테이블의 self 오브젝트도 같은 패턴이라 후보로 뜬다.
# 그건 ptr이 엔티티 테이블 범위 안에 있어서 구분한다.
# 엔티티 테이블 밖의 후보가 있으면 그게 플레이어 구조체일 가능성이 크다.
#
# 같은 폴더에 memread.py + mem.json이 있어야 한다.
# 실행: python diag_findself.py

import ctypes
import struct

import memread as mr

# VirtualQuery용
MEM_COMMIT = 0x1000
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
READABLE = (PAGE_READONLY, PAGE_READWRITE, PAGE_WRITECOPY,
            PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE)


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", ctypes.c_ulong),
        ("RegionSize", ctypes.c_size_t),
        ("State", ctypes.c_ulong),
        ("Protect", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
    ]


def find_self_struct():
    path, found, _tried = mr.findfile('mem.json')
    if not found:
        print('mem.json을 못 찾음')
        return
    mem = mr.Mem(path, lambda s: None)
    if not mem.attach(None):
        print('게임 붙기 실패:', mem.err)
        return
    objs, head, count = mem.entity_table()
    self_ent = None
    for o in objs:
        if o.get('id') == 1010177:
            self_ent = o
            break
    if self_ent is None:
        print('엔티티 테이블에서 씽씽(id 1010177)을 못 찾음')
        return
    self_id = self_ent['id']
    x_raw = self_ent['x']
    y_raw = self_ent['y']
    print('기준: self id=%d x_raw=%d y_raw=%d ent_ptr=0x%X' % (
        self_id, x_raw, y_raw, self_ent['ptr']))
    print('엔티티 테이블 head=0x%X count=%d' % (head, count))

    # 패턴: P+4=id, P+0x28=x_raw, P+0x2C=y_raw
    pat_id = struct.pack('<I', self_id)
    pat_x = struct.pack('<I', x_raw)
    pat_y = struct.pack('<I', y_raw)

    k32 = mr.k32
    h = mem.h
    mbi = MEMORY_BASIC_INFORMATION()
    addr = 0
    candidates = []
    # 32비트 프로세스: 0x00000000 ~ 0x7FFFFFFF
    while addr < 0x80000000:
        ret = k32.VirtualQueryEx(mr.wt.HANDLE(h), ctypes.c_void_p(addr),
                                 ctypes.byref(mbi), ctypes.sizeof(mbi))
        if ret == 0:
            break
        base = mbi.BaseAddress
        size = mbi.RegionSize
        if (mbi.State == MEM_COMMIT and mbi.Protect in READABLE
                and size > 0 and size < 0x40000000):
            # 1MB씩 나눠서 읽기
            off = 0
            while off < size:
                chunk = min(0x100000, size - off)
                data = mr.readmem(h, base + off, chunk)
                if data is None:
                    break
                # id 패턴 위치를 찾고 x/y 대조
                start = 0
                while True:
                    idx = data.find(pat_id, start)
                    if idx < 0:
                        break
                    # P = (base+off+idx) - 4  (id는 P+4에 있으므로)
                    p = base + off + idx - 4
                    # x/y 확인 (P+0x28, P+0x2C가 청크 안에 있어야 함)
                    need = idx - 4 + 0x30
                    if need <= len(data):
                        xv = struct.unpack_from('<I', data, idx - 4 + 0x28)[0]
                        yv = struct.unpack_from('<I', data, idx - 4 + 0x2C)[0]
                        if xv == x_raw and yv == y_raw:
                            candidates.append(p)
                    start = idx + 1
                off += chunk
        addr = base + size

    print('--- 후보 ---')
    if not candidates:
        print('후보 없음. self 구조체가 id/x/y를 이 레이아웃으로 안 들고 있거나, 스캔 범위 밖이다.')
    for p in candidates:
        # 엔티티 테이블 범위 안에 있는지
        in_table = head <= p < head + count * 0xD0
        tag = '엔티티 테이블 안 (self 오브젝트)' if in_table else '엔티티 테이블 밖 (플레이어 구조체 후보)'
        print('P=0x%X  %s' % (p, tag))
    print('--- 끝 ---')


if __name__ == '__main__':
    find_self_struct()
