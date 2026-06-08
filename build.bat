@echo off
chcp 65001 >nul
echo ========================================
echo   PaperLens - Build
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] Installing dependencies...
pip install -r requirements.txt pyinstaller -q
if errorlevel 1 (
    echo Dependency install failed!
    pause
    exit /b 1
)

echo.
echo [2/3] Building (may take 1-3 minutes)...
pyinstaller --onefile --windowed --name "PaperLens" ^
    --icon "static/icon.ico" ^
    --add-data "static;static" ^
    --add-data "config.yaml;." ^
    --hidden-import webview ^
    --hidden-import webview.platforms ^
    --hidden-import webview.platforms.edgechromium ^
    main.py

if errorlevel 1 (
    echo Build failed!
    pause
    exit /b 1
)

echo.
echo [3/3] Done!
echo.
echo Output: dist\PaperLens.exe
echo.
pause
