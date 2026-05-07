"""In-memory state for inspection sessions and Gemini API key.

Single-process / single-user assumption: dictionary keyed by inspection_id.
"""
from __future__ import annotations

import asyncio
from typing import Optional


_queues: dict[int, asyncio.Queue] = {}
_cancel_events: dict[int, asyncio.Event] = {}
_tasks: dict[int, asyncio.Task] = {}
_api_key: Optional[str] = None

# uploaded file registry: file_id -> (path_str, area, filename)
_uploaded_files: dict[str, tuple[str, str, str]] = {}


def register(inspection_id: int) -> None:
    _queues[inspection_id] = asyncio.Queue()
    _cancel_events[inspection_id] = asyncio.Event()


def get_queue(inspection_id: int) -> Optional[asyncio.Queue]:
    return _queues.get(inspection_id)


def get_cancel_event(inspection_id: int) -> Optional[asyncio.Event]:
    return _cancel_events.get(inspection_id)


def set_task(inspection_id: int, task: asyncio.Task) -> None:
    _tasks[inspection_id] = task


def get_task(inspection_id: int) -> Optional[asyncio.Task]:
    return _tasks.get(inspection_id)


def set_api_key(key: str) -> None:
    global _api_key
    _api_key = key


def get_api_key() -> Optional[str]:
    return _api_key


def register_upload(file_id: str, path: str, area: str, filename: str) -> None:
    _uploaded_files[file_id] = (path, area, filename)


def get_upload(file_id: str) -> Optional[tuple[str, str, str]]:
    return _uploaded_files.get(file_id)


def all_uploads() -> dict[str, tuple[str, str, str]]:
    return dict(_uploaded_files)


def remove_upload(file_id: str) -> None:
    _uploaded_files.pop(file_id, None)


def cleanup(inspection_id: int) -> None:
    _queues.pop(inspection_id, None)
    _cancel_events.pop(inspection_id, None)
    _tasks.pop(inspection_id, None)
