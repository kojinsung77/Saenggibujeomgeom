"""PyInstaller 단일 exe 진입점.

uvicorn 서버를 서브스레드에서 실행하고 브라우저를 자동으로 엽니다.
"""
from __future__ import annotations

import sys
import threading
import time
import webbrowser

import uvicorn


def _open_browser() -> None:
    time.sleep(3)
    webbrowser.open("http://127.0.0.1:8000")


if __name__ == "__main__":
    print("생활기록부 점검 프로그램을 시작합니다...")
    print("브라우저가 자동으로 열립니다. (약 3초 후)")
    print("종료하려면 이 창을 닫으세요.\n")

    threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="warning",
    )
