@echo off
cd /d "%~dp0"
echo ========================================
echo   PyTask Platform 启动器
echo ========================================

if not exist ".venv\Scripts\python.exe" (
    echo [setup] 首次运行，创建虚拟环境...
    python -m venv .venv
)

if not exist ".venv\.deps_installed" (
    echo [setup] 安装依赖...
    ".venv\Scripts\python" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [error] 依赖安装失败，请检查网络后重试
        pause
        exit /b 1
    )
    type nul > ".venv\.deps_installed"
)

echo [run] 启动平台: http://127.0.0.1:8000
".venv\Scripts\python" run.py
pause
