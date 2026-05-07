@echo off
chcp 65001 > nul
title 생기부점검 exe 빌드

echo ===================================
echo   생기부점검 exe 빌드 시작
echo ===================================
echo.

cd /d "%~dp0"

:: Python 확인
python --version > nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    pause & exit /b 1
)

:: 가상환경 활성화
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [준비] 가상환경 생성 중...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt --quiet
)

:: PyInstaller 설치 확인
pip show pyinstaller > nul 2>&1
if errorlevel 1 (
    echo [준비] PyInstaller 설치 중...
    pip install pyinstaller --quiet
)

:: 이전 빌드 정리
if exist "dist\생기부점검.exe" del /q "dist\생기부점검.exe"
if exist "build" rmdir /s /q "build"

:: 빌드 실행
echo [빌드] exe 생성 중... (3~10분 소요)
echo.
pyinstaller 생기부점검.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [오류] 빌드 실패. 위 오류 메시지를 확인하세요.
    pause & exit /b 1
)

echo.
echo ===================================
echo   빌드 완료!
echo ===================================
echo.
echo   dist\생기부점검.exe 파일이 생성됐습니다.
echo   이 파일을 선생님들께 배포하세요.
echo   (exe 파일 하나만 전달하면 됩니다)
echo.
pause
