# diag_selfptr.py
#
# self 포인터(DAT_005ab548, 0x5AB548)가 0으로 읽히는 원인을 찾는 진단 스크립트.
# 읽기만 한다. 게임 메모리를 바꾸지 않는다.
#
# 배경: sweep_mem.py 실행 시 "self 포인터가 0 (캐릭터 로딩 안 됨?)"이 뜬다.
# skillcast.py는 DAT_005ab548을 "self 구조체 포인터 변수"로 보고 [0x5AB548] 값을 읽는데,
# 그 값이 0이다. 두 가지 가설이 있다.
#   (H1) DAT_005ab548은 포인터 변수인데, 지금 0이다 (게임이 아직 안 세팅했거나 주소가 틀림).
#   (H2) DAT_005ab548은 포인터 변수가 아니라 구조체 그 자체다.
#        즉 self 구조체가 0x5AB548 주소에 바로 있고, ECX에는 0x5AB548(주소)을 넣어야 한다.
#        [0x5AB548]은 구조체의 첫 번째 필드라 0일 수 있다.
# 이 스크립트는 두 가설을 가르는 값을 읽어서 보여준다.
#   - [0x5AB548]          : 포인터 변수라면 self 구조체 주소, 구조체라면 첫 필드
#   - [0x5AB548 + 0x04]   : 구조체라면 self id (씽씽이면 1010177)
#   - [0x5AB548 + 0x28]   : 구조체라면 self x (raw)
#   - [0x5AB548 + 0x2C]   : 구조체라면 self y (raw)
#   - 엔티티 테이블의 self(씽씽) id/x/y : 대조용 (이건 sweep_mem이 이미 잘 찾고 있음)
#
# 판정:
#   - [0x5AB548+0x04] == 1010177 이고 x/y가 엔티티 테이블 self와 일치하면 H2 확정
#     → skillcast.py를 ECX = 0x5AB548(주소)로 고쳐야 한다.
#   - [0x5AB548]이 0이 아닌 주소이고, 그 주소+0x04가 1010177이면 H1 (포인터 변수 맞음)
#     → 0이었던 건 일시적인 문제거나 다른 원인. 그 값을 보면 된다.
#   - 둘 다 아니면 DAT_005ab548 주소 자체가 틀렸거나, self 구조체를 다른 데서 찾아야 한다.
#
# 같은 폴더에 memread.py + mem.json이 있어야 한다.
# 실행: python diag_selfptr.py

import struct

import memread as mr

SELF_ID = 1010177  # 씽씽
ADDR_SELF_PTR = 0x5AB548  # DAT_005ab548


def read_u32(mem, addr):
    """게임 메모리에서 4바이트(u32)를 읽는다. 못 읽으면 None.
    memread.Mem.object_bytes(절대주소, 4)로 직접 읽는다."""
    try:
        data = mem.object_bytes(addr, 4)
    except Exception:
        return None
    if data is None or len(data) < 4:
        return None
    return struct.unpack('<I', data[:4])[0]


def main():
    path, found, _tried = mr.findfile('mem.json')
    if not found:
        print('mem.json을 못 찾음 (스크립트 옆에 mem.json이 있어야 함)')
        return
    mem = mr.Mem(path, lambda s: None)
    if not mem.attach(None):
        print('게임 붙기 실패: ' + str(mem.err))
        return
    try:
        print('=== DAT_005ab548 (0x5AB548) 진단 ===')
        v0 = read_u32(mem, ADDR_SELF_PTR)
        print('[0x5AB548]        = %s' % (('0x%08X (%d)' % (v0, v0)) if v0 is not None else '읽기 실패'))
        v_id = read_u32(mem, ADDR_SELF_PTR + 0x04)
        print('[0x5AB548 + 0x04] = %s  (구조체라면 self id, 씽씽=1010177)' %
              (('0x%08X (%d)' % (v_id, v_id)) if v_id is not None else '읽기 실패'))
        v_x = read_u32(mem, ADDR_SELF_PTR + 0x28)
        print('[0x5AB548 + 0x28] = %s  (구조체라면 self x raw)' %
              (('0x%08X (%d)' % (v_x, v_x)) if v_x is not None else '읽기 실패'))
        v_y = read_u32(mem, ADDR_SELF_PTR + 0x2C)
        print('[0x5AB548 + 0x2C] = %s  (구조체라면 self y raw)' %
              (('0x%08X (%d)' % (v_y, v_y)) if v_y is not None else '읽기 실패'))
        # [0x5AB548]이 포인터라면 그 주소의 +0x04도 읽어본다
        if v0:
            pv_id = read_u32(mem, v0 + 0x04)
            print('[ptr+0x04]        = %s  ([0x5AB548]을 포인터로 봤을 때 self id)' %
                  (('0x%08X (%d)' % (pv_id, pv_id)) if pv_id is not None else '읽기 실패'))
            pv_x = read_u32(mem, v0 + 0x28)
            print('[ptr+0x28]        = %s  ([0x5AB548]을 포인터로 봤을 때 self x raw)' %
                  (('0x%08X (%d)' % (pv_x, pv_x)) if pv_x is not None else '읽기 실패'))
        # 엔티티 테이블 self 대조용
        print('=== 엔티티 테이블 self (대조용) ===')
        objs, _head, _count = mem.entity_table()
        for o in objs:
            if o['id'] == SELF_ID:
                from turnundead_mem import raw_to_game
                gx, gy = raw_to_game(o['x'], o['y'])
                print('self(씽씽) id=%d x_raw=%d y_raw=%d game=(%d,%d) ptr=0x%X' %
                      (o['id'], o['x'], o['y'], gx, gy, o['ptr']))
                break
        else:
            print('엔티티 테이블에서 self(씽씽, id 1010177)를 못 찾음')
        print('=== 판정 ===')
        if v_id == SELF_ID:
            print('H2 확정: DAT_005ab548은 구조체 그 자체다. ECX = 0x5AB548(주소)로 고쳐야 한다.')
        elif v0 and read_u32(mem, v0 + 0x04) == SELF_ID:
            print('H1: DAT_005ab548은 포인터 변수다. 지금은 값이 %s이다.' %
                  ('0x%08X' % v0))
        else:
            print('둘 다 아님: DAT_005ab548 주소 자체가 틀렸거나 self 구조체를 다른 데서 찾아야 한다.')
    finally:
        mem.detach()


if __name__ == '__main__':
    main()
