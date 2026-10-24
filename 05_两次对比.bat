@echo off
chcp 936 >nul
cd /d "%~dp0"

echo === 对比最近两份快照 ===
call ".venv\Scripts\activate.bat" >nul 2>&1
python -m probe.cli diff

echo.
echo 按任意键返回...
pause >nul
