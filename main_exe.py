"""PyInstaller 단일 exe 진입점.

uvicorn 서버를 서브스레드에서 실행하고 브라우저를 자동으로 엽니다.
"""
from __future__ import annotations

import sys
import threading
import time
import webbrowser

import uvicorn
from backend.main import app  # 문자열 대신 직접 import (frozen exe 호환)


def _open_browser() -> None:
    """서버가 실제로 응답할 때까지 기다린 후 브라우저를 열어 준다.
    PyInstaller 압축 해제 시간(최대 30초)을 감안한다."""
    import urllib.request
    url = "http://127.0.0.1:8000"
    for _ in range(60):          # 최대 60초 대기
        time.sleep(1)
        try:
            urllib.request.urlopen(url, timeout=1)
            break                # 응답 성공 → 즉시 브라우저 열기
        except Exception:
            pass
    webbrowser.open(url)


def _check_port(port: int) -> bool:
    """포트가 사용 가능한지 확인한다."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


if __name__ == "__main__":
    PORT = 8000

    if not _check_port(PORT):
        print("=" * 55)
        print("  [오류] 포트 8000이 이미 사용 중입니다.")
        print()
        print("  해결 방법:")
        print("  1. 이미 열려 있는 프로그램 창을 닫고 다시 실행하세요.")
        print("  2. 또는 작업관리자에서 python.exe 를 종료 후 재실행.")
        print("=" * 55)
        input("\n아무 키나 누르면 종료됩니다...")
        sys.exit(1)

    print("생활기록부 점검 프로그램을 시작합니다...")
    print("브라우저가 자동으로 열립니다. (약 3초 후)")
    print("종료하려면 이 창을 닫으세요.\n")

    threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=PORT,
        log_level="warning",
    )
