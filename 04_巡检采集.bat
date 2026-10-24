@echo off
chcp 936 >nul
cd /d "%~dp0"

echo === 巡检采集 ===
echo 清单文件都放在 probe\config\ 目录下。
echo 直接回车用 devices.local.yaml
set /p CFG=清单文件名 :
if "%CFG%"=="" set CFG=devices.local.yaml
call ".venv\Scripts\activate.bat" >nul 2>&1
python -m probe.cli collect --devices "probe\config\%CFG%"

echo.
echo 按任意键返回...
pause >nul
