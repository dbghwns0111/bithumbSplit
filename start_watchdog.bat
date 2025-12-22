@echo off
REM Watchdog 시작 배치 파일 (작업 스케줄러 등록용)

REM 현재 배치파일 위치로 이동
cd /d "%~dp0"

python watchdog.py
pause
