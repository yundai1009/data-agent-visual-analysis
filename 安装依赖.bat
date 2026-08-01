@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   数据分析 Agent 平台 - 依赖安装
echo ============================================
echo.
echo 正在安装 Python 依赖，请稍候...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [X] 安装失败
    echo     请确认已安装 Python，并且安装时勾选了
    echo     "Add python.exe to PATH"（重新安装一次即可）
) else (
    echo.
    echo [OK] 依赖安装完成！
    echo      现在双击 launch_gui.pyw 即可启动平台
)
echo.
pause
