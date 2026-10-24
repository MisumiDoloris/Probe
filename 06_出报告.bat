@echo off
chcp 936 >nul
cd /d "%~dp0"

echo === 生成巡检报告 ===
echo 单位名称、报告编号、签字人这些不用在这里填。
echo 报告出来是 Word，打印后手写补上就行。
echo.
set /p TAG=给这份报告起个短名方便区分，直接回车用默认名 :
call ".venv\Scripts\activate.bat" >nul 2>&1
if "%TAG%"=="" (
    python -m probe.cli report --diff
) else (
    python -m probe.cli report --diff --out "output\巡检报告_%TAG%.docx"
)
echo.
echo 报告在 output 目录里。

echo.
echo 按任意键返回...
pause >nul
