@echo off
chcp 936 >nul
cd /d "%~dp0"

:menu
cls
echo ==========================================
echo    probe 网络设备巡检工具
echo ==========================================
echo.
echo    1  首次安装环境（只跑一次）
echo    2  自测（不需要设备）
echo    3  探活扫描网段
echo    4  巡检采集
echo    5  两次对比
echo    6  生成巡检报告
echo    7  打开产出目录
echo    0  退出
echo.
set /p CH=输入序号后回车 :
if "%CH%"=="1" call "%~dp001_安装环境.bat"
if "%CH%"=="2" call "%~dp002_自测.bat"
if "%CH%"=="3" call "%~dp003_探活.bat"
if "%CH%"=="4" call "%~dp004_巡检采集.bat"
if "%CH%"=="5" call "%~dp005_两次对比.bat"
if "%CH%"=="6" call "%~dp006_出报告.bat"
if "%CH%"=="7" call "%~dp007_打开产出目录.bat"
if "%CH%"=="0" exit
goto menu
