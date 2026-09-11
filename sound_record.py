# -*- coding: utf-8 -*-
#=====================================================================
# 소리 계측 / 녹음 도구 (Windows 전용)
#
# 왜 필요한가 :
#   main.py 의 칼질 판정은 '음량 + 저음 비중' 두 개로만 가른다
#   그런데 몹이 나를 때리는 소리도 저음이 두꺼워서 같이 걸리는 일이 생긴다
#   임계를 감으로 옮기지 말고, 상황별로 실제 숫자를 재서 옮겨야 한다
#
# 쓰는 법 (게임 창을 띄워둔 채로 다른 콘솔에서) :
#   python sound_record.py 무음      10
#   python sound_record.py 몹만맞기   20
#   python sound_record.py 내칼질     20
#
#   -> sound_rec\<라벨>_<시각>.wav 로 저장되고,
#      끝날 때 그 구간의 dB / 저음% 통계와 '지금 설정이면 몇 % 를 칼질로 볼지' 를 찍는다
#
# main.py 를 그대로 import 해서 쓴다. 판정 함수와 임계를 복사하지 않아야
# 여기서 잰 숫자와 실제 매크로가 보는 숫자가 어긋나지 않는다
#=====================================================================
import os
import sys
import time
import wave

import main as M      #main.py 는 __main__ 가드가 있어서 import 해도 GUI 가 안 뜬다


def _fmt(vals, unit):
    vals = sorted(vals)
    n    = len(vals)
    if n == 0:
        return '값 없음'
    def pct(q):
        return vals[min(n - 1, int(n * q / 100.0))]
    return ('최소 %.1f / 25%% %.1f / 중앙 %.1f / 75%% %.1f / 최대 %.1f %s'
            % (vals[0], pct(25), pct(50), pct(75), vals[-1], unit))


def record(label, seconds):
    if not M.NUMPY_OK:
        print('numpy 가 없습니다')
        return
    try:
        import pyaudiowpatch as pa
    except ImportError:
        print('PyAudioWPatch 가 없습니다  (pip install PyAudioWPatch)')
        return

    p        = pa.PyAudio()
    dev, err = M._findloopback(p)
    if dev == None:
        print('루프백 장치를 못 엽니다 - ' + str(err))
        p.terminate()
        return

    rate = int(dev.get('defaultSampleRate', M.SND_RATE))
    ch   = int(dev.get('maxInputChannels', 2)) or 2
    st   = p.open(format=pa.paInt16, channels=ch, rate=rate, input=True,
                  input_device_index=dev['index'], frames_per_buffer=M.SND_FRAME)

    outdir = os.path.join(M.APP_DIR, 'sound_rec')
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    path = os.path.join(outdir, label + '_' + time.strftime('%Y%m%d_%H%M%S') + '.wav')
    wf   = wave.open(path, 'wb')
    wf.setnchannels(ch)
    wf.setsampwidth(2)
    wf.setframerate(rate)

    print('장치 : ' + str(dev.get('name')) + '  ' + str(rate) + 'Hz ' + str(ch) + 'ch')
    print('현재 임계 : %.0fdB 초과 + 저음 %.0f%% 초과' % (M.SND_FIGHT_DB, M.SND_FIGHT_LOW))
    print(str(seconds) + '초 녹음합니다. "' + label + '" 상황을 지금 만드세요...')

    framesec = float(M.SND_FRAME) / rate
    gate     = M.FightGate(framesec)
    window   = M._np.hanning(M.SND_FRAME)
    dbs      = []
    lows     = []
    fightsec = 0.0
    shown    = 0.0
    t0       = time.time()

    try:
        while time.time() - t0 < seconds:
            raw = st.read(M.SND_FRAME, exception_on_overflow=False)
            wf.writeframes(raw)

            buf = M._tomono(raw, ch)
            if len(buf) != len(window):
                window = M._np.hanning(len(buf))
            mag = M._np.abs(M._np.fft.rfft(buf * window))
            db  = M._rms_db(buf)
            low = M._lowratio(mag, rate)

            dbs.append(db)
            lows.append(low)
            if gate.push(db, low):
                fightsec += framesec

            #0.5초마다 지금 값을 보여준다. 게임 화면을 보면서 눈으로 맞출 수 있게
            el = time.time() - t0
            if el - shown >= 0.5:
                shown = el
                print('  %5.1fs  %6.1fdB  저음 %4.1f%%  %s'
                      % (el, gate.avgdb, gate.avglow, '칼질' if gate.fight else '-'))
    except KeyboardInterrupt:
        print('\n중단됨')
    finally:
        st.stop_stream()
        st.close()
        p.terminate()
        wf.close()

    dur = max(1e-9, time.time() - t0)
    print('')
    print('저장 : ' + path)
    print('음량   : ' + _fmt(dbs,  'dB'))
    print('저음   : ' + _fmt(lows, '%'))
    print('현재 설정이면 이 구간의 %.0f%% 를 칼질로 봅니다  (%.1fs / %.1fs)'
          % (100.0 * fightsec / dur, fightsec, dur))
    print('')
    print('판단 기준 : "내칼질" 은 이 값이 높아야 하고, "몹만맞기" 와 "무음" 은 0%% 여야 합니다')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('사용법 : python sound_record.py <라벨> [초]')
        print('  예   : python sound_record.py 몹만맞기 20')
        sys.exit(1)
    lab = sys.argv[1]
    sec = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    record(lab, sec)
