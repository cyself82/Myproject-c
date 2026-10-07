@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo SOXL 실시간 화면을 여는 중입니다... 잠시 후 창이 열립니다.
echo 이 검은 창을 닫으면 실시간 갱신이 멈춥니다. (미국장 마감 후에는 자동으로 끝납니다)
.venv\Scripts\python.exe soxl_signal.py --live %* >nul
if errorlevel 1 (echo 실행 중 오류가 났습니다. & pause)
