@echo off
chcp 936 >nul
cd /d "%~dp0"

if not exist output mkdir output
start "" explorer "%~dp0output"
if exist snapshots start "" explorer "%~dp0snapshots"
exit
