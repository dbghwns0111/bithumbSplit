@echo off
REM Watchdog 시작 배치 파일
REM 이 파일을 작업 스케줄러에 등록하면 자동 실행됩니다

cd /d C:\Users\USER\VS_CODE\BithumbSplit
python watchdog.py
pause
