@echo off
chcp 65001 > nul
REM ====================================================================
REM  Build pit.py (memory-based macro) into exe files. Windows only.
REM
REM    dist\pit_auto.exe   hunting macro (GUI)
REM    dist\findme.exe     BEST: finds HP via character name (console)
REM    dist\hpfind.exe     alternative: finds HP by repeated damage (console)
REM    dist\memprobe.exe   memory probe / value search / watch (console)
REM    dist\memcalib.exe   world-to-screen calibration (console)
REM
REM  NOTE: keep this file ASCII-only and CRLF. cmd.exe rewinds the batch
REM  file by byte offset, so multi-byte characters make it lose the line
REM  boundary and execute the tail of a line as a command.
REM  Korean instructions live in NEXTSTEPS.txt and are printed at the end.
REM
REM  build_exe.bat (main.py) is untouched.
REM ====================================================================

echo [1/5] Installing required packages
pip install pyinstaller pyautogui pywin32 keyboard pillow opencv-python PyAudioWPatch
if errorlevel 1 goto fail

echo.
echo [2/5] Building pit_auto.exe (GUI)
REM main.py is pulled in automatically because pit.py imports it
pyinstaller --noconfirm --clean ^
    --onefile ^
    --windowed ^
    --name pit_auto ^
    --add-data "image;image" ^
    pit.py
if errorlevel 1 goto fail

echo.
echo [3/5] Building memprobe.exe (console)
pyinstaller --noconfirm --clean ^
    --onefile ^
    --console ^
    --name memprobe ^
    memprobe.py
if errorlevel 1 goto fail

echo.
echo [4/5] Building hpfind.exe and memcalib.exe (console)
pyinstaller --noconfirm --clean ^
    --onefile ^
    --console ^
    --name hpfind ^
    hpfind.py
if errorlevel 1 goto fail
pyinstaller --noconfirm --clean ^
    --onefile ^
    --console ^
    --name findme ^
    findme.py
if errorlevel 1 goto fail

pyinstaller --noconfirm --clean ^
    --onefile ^
    --console ^
    --name memcalib ^
    memcalib.py
if errorlevel 1 goto fail

echo.
echo [5/5] Copying image folder, mem.json and NEXTSTEPS.txt next to dist
REM mem.json must stay OUTSIDE the exe: offsets change on every client
REM patch, so it has to be editable with Notepad.
if not exist dist\image mkdir dist\image
xcopy /Y /E /I image dist\image > nul
copy /Y NEXTSTEPS.txt dist\NEXTSTEPS.txt > nul
if exist dist\mem.json (
    echo   dist\mem.json already exists - keeping your offsets
) else (
    copy /Y mem.json dist\mem.json > nul
    echo   dist\mem.json created
)

echo.
echo Build complete.
echo.
type NEXTSTEPS.txt
echo.
goto end

:fail
echo.
echo BUILD FAILED

:end
pause
