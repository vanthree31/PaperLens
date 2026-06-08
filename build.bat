@echo off
chcp 65001 >nul
echo ========================================
echo   文献检索智能体 - 一键打包
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] 安装依赖...
pip install -r requirements.txt pyinstaller -q
if errorlevel 1 (
    echo 依赖安装失败！
    pause
    exit /b 1
)

echo.
echo [2/3] 打包中（可能需要 1-3 分钟）...
pyinstaller --onefile --windowed --name "PaperLens" ^
    --add-data "static;static" ^
    --add-data "config.yaml;." ^
    --hidden-import webview ^
    --hidden-import webview.platforms ^
    --hidden-import webview.platforms.edgechromium ^
    main.py

if errorlevel 1 (
    echo 打包失败！
    pause
    exit /b 1
)

echo.
echo [3/3] 完成！
echo.
echo 生成文件: dist\文献检索.exe
echo 双击即可运行，无需 Python 环境。
echo.
pause
