@echo off
chcp 936 >nul
cd /d "%~dp0"

echo === 探活扫描 ===
set /p NET=输入要扫的网段，直接回车用 192.168.56.0/24 :
if "%NET%"=="" set NET=192.168.56.0/24
call ".venv\Scripts\activate.bat" >nul 2>&1
python -m probe.cli sweep --network %NET%

echo.
echo 按任意键返回...
pause >nul
