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
if errorlevel 2 goto badcfg
if errorlevel 1 goto allfail
echo.
echo 采完了。接着双击 05 对比、06 出报告。
goto end
:badcfg
echo.
echo 清单有问题，这一批一台都没采。上面列着第几条、哪台、哪个字段错，改好再跑。
goto end
:allfail
echo.
echo 一台都没采到。快照和台账里全是空的，别拿去出报告。
:end
echo.
echo 按任意键返回...
pause >nul
