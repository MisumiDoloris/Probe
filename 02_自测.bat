@echo off
chcp 936 >nul
cd /d "%~dp0"

echo === 自测（不需要任何设备）===
call ".venv\Scripts\activate.bat" >nul 2>&1
python -m unittest discover -s tests -v

echo.
echo 按任意键返回...
pause >nul
