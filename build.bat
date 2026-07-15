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
python -m PyInstaller --clean --onefile --windowed --name "PaperLens" ^
    --paths "." ^
    --icon "static/icon.ico" ^
    --add-data "static;static" ^
    --add-data "config.yaml;." ^
    --add-data "routes;routes" ^
    --add-data "core;core" ^
    --hidden-import server ^
    --hidden-import search_engine ^
    --hidden-import access_proxy ^
    --hidden-import ai_assistant ^
    --hidden-import exporters ^
    --hidden-import dedup ^
    --hidden-import citation_formatter ^
    --hidden-import schema_migrate ^
    --hidden-import core ^
    --hidden-import core.config ^
    --hidden-import core.state ^
    --hidden-import core.utils ^
    --hidden-import core.cache ^
    --hidden-import routes ^
    --hidden-import routes.search ^
    --hidden-import routes.ai ^
    --hidden-import routes.collections ^
    --hidden-import routes.export ^
    --hidden-import routes.graph ^
    --hidden-import routes.history ^
    --hidden-import routes.system ^
    --hidden-import routes.zotero ^
    --hidden-import routes.carsi ^
    --hidden-import routes.wanfang ^
    --hidden-import routes.tags ^
    --hidden-import webview ^
    --hidden-import webview.platforms ^
    --hidden-import webview.platforms.edgechromium ^
    --hidden-import playwright ^
    --hidden-import playwright._impl ^
    --hidden-import playwright._impl._driver ^
    --hidden-import playwright.sync_api ^
    --hidden-import playwright.async_api ^
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
