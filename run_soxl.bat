@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo SOXL 데이터를 불러오는 중입니다... 잠시 후 브라우저에 결과가 열립니다.
.venv\Scripts\python.exe soxl_signal.py --report %* >nul
if errorlevel 1 (echo 실행 중 오류가 났습니다. & pause)
