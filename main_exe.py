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


if __name__ == "__main__":
    print("생활기록부 점검 프로그램을 시작합니다...")
    print("브라우저가 자동으로 열립니다. (약 3초 후)")
    print("종료하려면 이 창을 닫으세요.\n")

    threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="warning",
    )
