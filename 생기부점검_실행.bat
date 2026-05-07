@echo off
chcp 65001 > nul
title 생활기록부 점검 프로그램

echo ===================================
echo   생활기록부 점검 프로그램 시작
echo ===================================
echo.

cd /d "%~dp0"

:: Python 설치 확인
python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo.
    echo  1. https://www.python.org 접속
    echo  2. Download Python 3.11 이상 클릭
    echo  3. 설치 시 "Add Python to PATH" 반드시 체크
    echo  4. 설치 완료 후 이 파일 다시 실행
    echo.
    pause
    exit /b 1
)

:: 가상환경이 없으면 자동 생성 + 패키지 설치
if not exist ".venv\Scripts\activate.bat" (
    echo [준비] 처음 실행입니다. 자동으로 환경을 설정합니다.
    echo       인터넷 연결이 필요하며 3~5분 소요됩니다.
    echo.

    python -m venv .venv
    if errorlevel 1 (
        echo [오류] 가상환경 생성 실패. 관리자 권한으로 실행해보세요.
        pause
        exit /b 1
    )

    call .venv\Scripts\activate.bat
    pip install -r requirements.txt --quiet --no-warn-script-location
    if errorlevel 1 (
        echo [오류] 패키지 설치 실패.
        echo       인터넷 연결을 확인하고 다시 시도해주세요.
        pause
        exit /b 1
    )
    echo [완료] 환경 설정이 끝났습니다.
    echo.
) else (
    call .venv\Scripts\activate.bat
)

:: 포트 8000이 이미 사용 중이면 바로 브라우저만 열기
netstat -an 2>nul | findstr ":8000 " | findstr "LISTENING" > nul 2>&1
if not errorlevel 1 (
    echo [안내] 서버가 이미 실행 중입니다. 브라우저를 엽니다.
    start http://127.0.0.1:8000
    echo.
    echo 종료하려면 아무 키나 누르세요.
    pause > nul
    exit /b 0
)

:: 서버 시작 (별도 창)
echo [시작] 서버를 시작합니다...
start "생기부점검 서버 (닫으면 종료)" python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

:: 서버 준비될 때까지 대기 (최대 15초)
echo [대기] 서버 준비 중입니다
set /a count=0

:wait_loop
timeout /t 1 /nobreak > nul
set /a count+=1
<nul set /p ="."
curl -s --max-time 1 http://127.0.0.1:8000/healthz > nul 2>&1
if not errorlevel 1 goto server_ready
if %count% geq 15 goto timeout_error
goto wait_loop

:server_ready
echo.
echo [완료] 서버가 준비됐습니다! 브라우저를 엽니다.
echo.
start http://127.0.0.1:8000

echo  브라우저가 열렸습니다.
echo  프로그램을 종료하려면 "생기부점검 서버" 창을 닫으세요.
echo.
pause > nul
exit /b 0

:timeout_error
echo.
echo [오류] 서버가 시작되지 않았습니다.
echo.
echo  가능한 원인:
echo  1. 포트 8000이 다른 프로그램에서 사용 중
echo  2. 방화벽이 차단 중
echo  3. 패키지가 제대로 설치되지 않음 (.venv 폴더 삭제 후 재시도)
echo.
echo  logs\app.log 파일에서 상세 오류를 확인할 수 있습니다.
echo.
pause
exit /b 1
