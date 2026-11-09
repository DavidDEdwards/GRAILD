@echo off
setlocal
cd /d "%~dp0"
set "BUILD_RESULT=0"
echo ========================================
echo Building JuiceSpot .exe automatically...
echo ========================================
py -3.13 -m pip install -r requirements.txt
if errorlevel 1 goto build_failed

set "BUILD_TEMP=%TEMP%\JuiceSpotBuild-%RANDOM%-%RANDOM%"
mkdir "%BUILD_TEMP%\work"
mkdir "%BUILD_TEMP%\spec"
if errorlevel 1 goto build_failed

echo Building the standalone signed-update installer...
py -3.13 -m PyInstaller --noconfirm --clean --noconsole --onefile --name GRAILDUpdater --icon "%~dp0assets\graild.ico" --distpath "%BUILD_TEMP%\dist" --workpath "%BUILD_TEMP%\work" --specpath "%BUILD_TEMP%\spec" graild_updater.py
if errorlevel 1 goto build_failed
py -3.13 "%~dp0publish_build.py" "%BUILD_TEMP%\dist\GRAILDUpdater.exe" "%~dp0dist\GRAILDUpdater.exe"
if errorlevel 1 goto build_failed

py -3.13 -m PyInstaller --noconfirm --clean --noconsole --onefile --icon "%~dp0assets\graild.ico" --hidden-import=pygame --collect-all pygame --collect-all webview --collect-all imageio_ffmpeg --collect-data certifi --add-data "%~dp0index.html;." --add-data "%~dp0assets;assets" --add-data "%~dp0canary_ui.js;." --add-data "%~dp0update_ui.js;." --add-data "%BUILD_TEMP%\dist\GRAILDUpdater.exe;." --distpath "%BUILD_TEMP%\dist" --workpath "%BUILD_TEMP%\work" --specpath "%BUILD_TEMP%\spec" JuiceGuesserMain.py
if errorlevel 1 goto build_failed

echo.
py -3.13 "%~dp0publish_build.py" "%BUILD_TEMP%\dist\JuiceGuesserMain.exe" "%~dp0dist\JuiceGuesserMain.exe"
if errorlevel 1 goto build_failed
goto finish

:build_failed
set "BUILD_RESULT=1"
echo.
echo Build failed. Check the error messages above.

:finish
if /i "%~1"=="--no-pause" goto done
pause
:done
exit /b %BUILD_RESULT%