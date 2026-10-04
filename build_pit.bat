@echo off
chcp 65001 > nul
REM ====================================================================
REM  pit.py (메모리 기반) 를 exe 로 묶는다 (Windows 에서만 실행)
REM  결과물 : dist\pit_auto.exe     사냥 매크로 본체 (GUI)
REM           dist\memprobe.exe     메모리 읽기 가능한지 진단 / 값 확인
REM           dist\memcalib.exe     월드->화면 변환 실측
REM
REM  main.py 빌드는 build_exe.bat 가 그대로 담당한다. 이 파일은 건드리지 않는다
REM ====================================================================

echo [1/5] 필요한 패키지 설치
pip install pyinstaller pyautogui pywin32 keyboard pillow opencv-python PyAudioWPatch
if errorlevel 1 goto fail

echo.
echo [2/5] pit_auto.exe 빌드 (GUI)
REM main.py 는 pit.py 가 import 하므로 자동으로 함께 들어간다
pyinstaller --noconfirm --clean ^
    --onefile ^
    --windowed ^
    --name pit_auto ^
    --add-data "image;image" ^
    pit.py
if errorlevel 1 goto fail

echo.
echo [3/5] memprobe.exe 빌드 (콘솔)
REM 진단 도구는 출력을 봐야 하므로 --console 로 묶는다
pyinstaller --noconfirm --clean ^
    --onefile ^
    --console ^
    --name memprobe ^
    memprobe.py
if errorlevel 1 goto fail

echo.
echo [4/5] memcalib.exe 빌드 (콘솔)
pyinstaller --noconfirm --clean ^
    --onefile ^
    --console ^
    --name memcalib ^
    memcalib.py
if errorlevel 1 goto fail

echo.
echo [5/5] image 폴더와 mem.json 을 dist 옆에 복사
REM mem.json 은 exe 안에 넣지 않는다. 클라이언트 패치마다 오프셋을 고쳐야 하므로
REM 반드시 exe 옆에 두고 메모장으로 열어 수정할 수 있게 한다
if not exist dist\image mkdir dist\image
xcopy /Y /E /I image dist\image > nul
if exist dist\mem.json (
    echo   dist\mem.json 이 이미 있다 - 덮어쓰지 않는다 ^(채워둔 오프셋 보존^)
) else (
    copy /Y mem.json dist\mem.json > nul
    echo   dist\mem.json 생성
)

echo.
echo 완료
echo   dist\pit_auto.exe   사냥 매크로 ^(메모리^)
echo   dist\memprobe.exe   먼저 이걸 돌려서 읽기가 되는지 확인한다
echo   dist\memcalib.exe   몹 타겟을 쓸 때만 필요하다
echo.
echo 순서 :
echo   1. memprobe.exe --list        클라이언트 PID 찾기
echo   2. memprobe.exe --pid ^<PID^>   읽기 가능한지 판정
echo   3. mem.json 에 오프셋 채우기
echo   4. memprobe.exe --watch hp,hp_max   값이 따라 움직이는지 확인
echo   5. pit_auto.exe 에서 메모리 감지 켜기
echo.
echo   config.json / pit.json 은 exe 를 처음 실행하고 [설정 저장] 을 누르면 생긴다
echo   게임이 관리자 권한으로 돌면 exe 도 관리자 권한으로 실행해야 한다
goto end

:fail
echo.
echo 빌드 실패

:end
pause
