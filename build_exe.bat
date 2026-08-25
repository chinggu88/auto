@echo off
chcp 65001 > nul
REM ====================================================================
REM  main.py 를 단일 exe 로 묶는다 (Windows 에서만 실행)
REM  결과물 : dist\lin_auto.exe
REM ====================================================================

echo [1/3] 필요한 패키지 설치
pip install pyinstaller pyautogui pywin32 keyboard pillow opencv-python PyAudioWPatch
if errorlevel 1 goto fail

echo.
echo [2/3] exe 빌드
REM --onefile   : exe 하나로 묶기
REM --windowed  : 콘솔 창 안 띄우기 (GUI 만)
REM --add-data  : image 폴더를 exe 안에 넣기 (exe 옆에 image\ 가 있으면 그쪽이 우선)
pyinstaller --noconfirm --clean ^
    --onefile ^
    --windowed ^
    --name lin_auto ^
    --add-data "image;image" ^
    main.py
if errorlevel 1 goto fail

echo.
echo [3/3] image 폴더를 dist 옆에 복사 (해상도 바뀌면 여기 PNG 만 갈아끼우면 됨)
if not exist dist\image mkdir dist\image
xcopy /Y /E /I image dist\image > nul

echo.
echo 완료 : dist\lin_auto.exe
echo   - config.json 은 exe 를 처음 실행하고 [설정 저장] 을 누르면 exe 옆에 생긴다
echo   - 게임이 관리자 권한으로 돌면 exe 도 관리자 권한으로 실행해야 키 입력이 먹는다
goto end

:fail
echo.
echo 빌드 실패

:end
pause
