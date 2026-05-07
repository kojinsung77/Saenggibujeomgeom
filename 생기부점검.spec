# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 생활기록부 점검 프로그램 단일 exe 빌드."""

from pathlib import Path
import sys

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "main_exe.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # 프론트엔드 정적 파일
        (str(ROOT / "frontend"), "frontend"),
        # 규칙 JSON 파일
        (str(ROOT / "rules"), "rules"),
        # DB 스키마
        (str(ROOT / "backend" / "db" / "schema.sql"), "backend/db"),
    ],
    hiddenimports=[
        # uvicorn
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # anyio
        "anyio",
        "anyio._backends._asyncio",
        # fastapi / starlette
        "fastapi",
        "starlette",
        "starlette.routing",
        "starlette.staticfiles",
        "starlette.responses",
        "starlette.middleware.cors",
        # pydantic
        "pydantic",
        "pydantic.deprecated.class_validators",
        "pydantic.v1",
        # pandas / openpyxl / xlrd
        "pandas",
        "openpyxl",
        "xlrd",
        "xlsxwriter",
        # multipart
        "multipart",
        "python_multipart",
        # aiofiles
        "aiofiles",
        # google-generativeai (선택적)
        "google.generativeai",
        # dotenv
        "dotenv",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "PIL", "cv2"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="생기부점검",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,       # 콘솔 창 표시 (오류 확인용)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,          # ico 파일이 있으면 경로 지정: icon="icon.ico"
)
