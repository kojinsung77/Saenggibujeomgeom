@echo off
chcp 65001 > nul
title 생기부점검 exe 빌드

echo ===============================
echo   생기부점검 exe 빌드
echo ===============================
echo.

cd /d "%~dp0"

:: ── Python 확인 ─────────────────────────────────────────────
python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python을 찾을 수 없습니다.
    echo   python.org 에서 Python 설치 후 재실행하세요.
    pause
    exit /b 1
)
echo [확인] Python 버전:
python --version
echo.

:: ── 가상환경 활성화 ──────────────────────────────────────────
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
    echo [확인] 가상환경 활성화 완료
) else (
    echo [준비] 가상환경 생성 중...
    python -m venv .venv
    call ".venv\Scripts\activate.bat"
    echo [준비] 패키지 설치 중...
    pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo [오류] 패키지 설치 실패
        pause
        exit /b 1
    )
)
echo.

:: ── PyInstaller 설치 ─────────────────────────────────────────
python -m pip show pyinstaller > nul 2>&1
if errorlevel 1 (
    echo [준비] PyInstaller 설치 중...
    python -m pip install pyinstaller --quiet
    if errorlevel 1 (
        echo [오류] PyInstaller 설치 실패 - 인터넷 연결을 확인하세요.
        pause
        exit /b 1
    )
    echo [확인] PyInstaller 설치 완료
) else (
    echo [확인] PyInstaller 이미 설치됨
)
echo.

:: ── 이전 빌드 정리 ───────────────────────────────────────────
if exist "dist\생기부점검.exe" (
    echo [정리] 이전 빌드 파일 삭제 중...
    del /q "dist\생기부점검.exe"
)
if exist "build" rmdir /s /q "build"

:: ── 빌드 실행 ────────────────────────────────────────────────
echo [빌드] exe 파일을 생성합니다. (3~10분 소요)
echo        이 창을 닫지 마세요.
echo.

python -m PyInstaller 생기부점검.spec --noconfirm

if errorlevel 1 (
    echo.
    echo ──────────────────────────────────────────
    echo [오류] 빌드에 실패했습니다.
    echo       위 오류 메시지를 확인하세요.
    echo ──────────────────────────────────────────
    pause
    exit /b 1
)

echo.
echo ===============================
echo   빌드 성공!
echo ===============================
echo.
echo   dist\생기부점검.exe 가 생성됐습니다.
echo.
echo   이 파일 하나만 다른 선생님께 전달하면
echo   Python 설치 없이 바로 사용 가능합니다.
echo.
pause
