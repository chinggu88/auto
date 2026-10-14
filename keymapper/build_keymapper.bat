@echo off
chcp 65001 > nul
REM ====================================================================
REM  keymapper.py 를 단일 exe 로 묶는다 (Windows 에서만 실행)
REM  결과물 : dist\keymapper.exe
REM ====================================================================

echo [1/2] 필요한 패키지 설치
pip install --user pyinstaller keyboard
if errorlevel 1 goto fail

echo.
echo [2/2] exe 빌드
REM --onefile   : exe 하나로 묶기
REM --windowed  : 콘솔 창 안 띄우기 (GUI 만)
python -m PyInstaller --noconfirm --clean ^
    --onefile ^
    --windowed ^
    --name keymapper ^
    keymapper.py
if errorlevel 1 goto fail

echo.
echo 완료 : dist\keymapper.exe
goto end

:fail
echo.
echo [실패] 위 오류를 확인하세요.
:end
pause
