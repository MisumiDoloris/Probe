@echo off
chcp 936 >nul
cd /d "%~dp0"

echo === 首次安装环境 ===
echo 只需要跑一次。会建 .venv 并把六个依赖装进去。
echo.
if not exist ".venv" (
    python -m venv .venv
    if errorlevel 1 (
        echo 建虚拟环境失败，先确认 Python 装好并且勾了 Add to PATH。
        goto end
    )
)
call ".venv\Scripts\activate.bat"
pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
:end

echo.
echo 按任意键返回...
pause >nul
