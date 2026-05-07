@echo off
chcp 65001 > nul
title 생활기록부 점검 프로그램

echo ===============================
echo   생활기록부 점검 프로그램
echo ===============================
echo.

cd /d "%~dp0"

:: ── Python 확인 ─────────────────────────────────────────────
python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python을 찾을 수 없습니다.
    echo.
    echo   1. https://www.python.org 접속
    echo   2. "Download Python 3.11 이상" 클릭하여 설치
    echo   3. 설치 시 "Add Python to PATH" 반드시 체크!
    echo   4. 설치 완료 후 이 파일 다시 실행
    echo.
    pause
    exit /b 1
)

:: ── 가상환경 없으면 자동 생성 ────────────────────────────────
if not exist ".venv\Scripts\activate.bat" (
    echo [준비] 처음 실행입니다. 필요한 환경을 설치합니다.
    echo       인터넷 연결 필요 / 약 3-5분 소요
    echo.
    python -m venv .venv
    if errorlevel 1 (
        echo [오류] 가상환경 생성 실패
        pause
        exit /b 1
    )
    call ".venv\Scripts\activate.bat"
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [오류] 패키지 설치 실패 - 인터넷 연결을 확인하세요.
        pause
        exit /b 1
    )
    echo.
    echo [완료] 환경 설정이 끝났습니다.
    echo.
) else (
    call ".venv\Scripts\activate.bat"
)

:: ── 이미 실행 중인지 확인 ─────────────────────────────────────
netstat -an | findstr ":8000" | findstr "LISTENING" > nul 2>&1
if not errorlevel 1 (
    echo [안내] 서버가 이미 실행 중입니다.
    echo.
    echo   브라우저에서 아래 주소를 열어주세요:
    echo   http://127.0.0.1:8000
    echo.
    start "" "http://127.0.0.1:8000"
    echo 아무 키나 누르면 이 창이 닫힙니다.
    pause
    exit /b 0
)

:: ── 서버 시작 (현재 창에서 실행 — 닫으면 서버 종료) ──────────
echo [시작] 서버를 시작합니다...
echo.
echo   잠시 후 브라우저가 자동으로 열립니다.
echo   이 창을 닫으면 서버가 함께 종료됩니다.
echo ──────────────────────────────────────────
echo.

:: 3초 후 브라우저를 백그라운드에서 열기
start "" /b cmd /c "timeout /t 3 /nobreak > nul && start "" http://127.0.0.1:8000"

:: 서버를 현재 창에서 실행 (오류가 바로 보임)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

echo.
echo ──────────────────────────────────────────
echo [종료] 서버가 종료됐습니다.
pause
