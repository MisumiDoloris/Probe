@echo off
chcp 936 >nul
cd /d "%~dp0"

echo === 现场录入 ===
echo 账号和密码不写进文件，只存在这台机器的环境变量里，跑完就清掉。
echo 换一个现场就重跑这支，不用去改清单。
echo.
set /p IP=设备地址（直接回车用 192.168.56.10）:
if "%IP%"=="" set IP=192.168.56.10
set /p PORT=端口（直接回车用 22）:
if "%PORT%"=="" set PORT=22
set /p BRAND=品牌 huawei/h3c/ruijie/cisco（直接回车用 huawei）:
if "%BRAND%"=="" set BRAND=huawei
set /p USR=用户名 :
set /p PWD=密码（输入时看得见，回车后自动清屏）:
cls

set PROBE_USER=%USR%
set PROBE_PASS=%PWD%

> "probe\config\devices.bat.yaml" echo devices:
>> "probe\config\devices.bat.yaml" echo   - name: onsite
>> "probe\config\devices.bat.yaml" echo     ip: %IP%
>> "probe\config\devices.bat.yaml" echo     port: %PORT%
>> "probe\config\devices.bat.yaml" echo     method: ssh
>> "probe\config\devices.bat.yaml" echo     brand: %BRAND%
>> "probe\config\devices.bat.yaml" echo     username_env: PROBE_USER
>> "probe\config\devices.bat.yaml" echo     password_env: PROBE_PASS

echo 正在采集 %IP%:%PORT% ...
call ".venv\Scripts\activate.bat" >nul 2>&1
python -m probe.cli collect --devices "probe\config\devices.bat.yaml"
set RC=%ERRORLEVEL%

set PROBE_USER=
set PROBE_PASS=
set PWD=
set USR=

if "%RC%"=="2" goto badlist
if "%RC%"=="1" goto allfail
echo.
echo 采完了。接着双击 06 出报告。
goto end

:badlist
echo.
echo 清单有问题，这一台都没采。按上面那行改，或者用 04 换成写得好的清单。
goto end

:allfail
echo.
echo 一台都没采到。看上面那行原因：最常见是账号密码不对，其次是设备没开 SSH、
echo 或者老 VRP 上少了 ssh user 那两条（见 README 的已知的坑）。
:end
echo.
echo 按任意键返回...
pause >nul
