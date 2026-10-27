@echo off
chcp 936 >nul
cd /d "%~dp0"

echo === 现场录入 ===
echo 账号、密码、团体字都不写进文件，只存在这台机器的环境变量里，跑完就清掉。
echo 换一个现场就重跑这支，不用去改清单。
echo.
echo 采集方式：
echo    1  SSH    （默认，能取到配置回显）
echo    2  Telnet （老设备没有 SSH 才用）
echo    3  SNMP   （只读最安全，但取不到配置回显）
set /p M=选一个（直接回车用 1）:
if "%M%"=="" set M=1
if "%M%"=="1" set METH=ssh
if "%M%"=="2" set METH=telnet
if "%M%"=="3" set METH=snmp
if "%METH%"=="" set METH=ssh

set /p IP=设备地址（直接回车用 192.168.56.10）:
if "%IP%"=="" set IP=192.168.56.10

if "%METH%"=="snmp" goto snmp_port
if "%METH%"=="telnet" goto telnet_port

set /p PORT=端口（直接回车用 22）:
if "%PORT%"=="" set PORT=22
goto ask_login

:telnet_port
set /p PORT=端口（直接回车用 23）:
if "%PORT%"=="" set PORT=23
goto ask_login

:snmp_port
set /p PORT=端口（直接回车用 161）:
if "%PORT%"=="" set PORT=161
goto ask_snmp

:ask_login
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
>> "probe\config\devices.bat.yaml" echo     method: %METH%
>> "probe\config\devices.bat.yaml" echo     brand: %BRAND%
>> "probe\config\devices.bat.yaml" echo     username_env: PROBE_USER
>> "probe\config\devices.bat.yaml" echo     password_env: PROBE_PASS
goto run

:ask_snmp
set /p COMM=只读团体字（直接回车用 public）:
if "%COMM%"=="" set COMM=public
cls
set PROBE_COMM=%COMM%

> "probe\config\devices.bat.yaml" echo devices:
>> "probe\config\devices.bat.yaml" echo   - name: onsite
>> "probe\config\devices.bat.yaml" echo     ip: %IP%
>> "probe\config\devices.bat.yaml" echo     port: %PORT%
>> "probe\config\devices.bat.yaml" echo     method: snmp
>> "probe\config\devices.bat.yaml" echo     community_env: PROBE_COMM
goto run

:run
echo 正在采集 %IP%:%PORT%（方式 %METH%）...
call ".venv\Scripts\activate.bat" >nul 2>&1
python -m probe.cli collect --devices "probe\config\devices.bat.yaml"
set RC=%ERRORLEVEL%

set PROBE_USER=
set PROBE_PASS=
set PROBE_COMM=
set PWD=
set USR=
set COMM=

if "%RC%"=="2" goto badlist
if "%RC%"=="1" goto allfail
echo.
echo 采完了。接着选 6 出报告。
goto end

:badlist
echo.
echo 清单有问题，这一台都没采。按上面那行改，或者用 4 换成写好的清单。
goto end

:allfail
echo.
echo 一台都没采到。看上面那行原因：SSH 最常见是账号密码不对，或者老 VRP 少了
echo ssh user 那两条；Telnet 多半是端口或 vty 没允许；SNMP 是团体字或设备没开
echo snmp-agent（还要看有没有配 snmp-agent protocol source-interface）。
:end
echo.
echo 按任意键返回...
pause >nul
