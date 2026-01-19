
#!/usr/bin/env python3
"""
**SessionLogger.py**
Created: December 2026
Edited: January 2026
Created by: Prajeet (DDoS Response Team)

Session-logging utility that writes timestamped entries to a per-user,
per-run log file (session_logs/SESSION_<date>_<time>_<user>.log). 
It uses a background thread and a queue so logging calls do not block
the main program. Supports plain lines, titled blocks, and JSON payloads;
handles directory creation and graceful shutdown.
"""
from __future__ import annotations
import os
import time
import json
import sys
import queue
import threading
from typing import Optional

"""
    Return the base directory of the application.
    - If packaged (PyInstaller/cx_Freeze), use the folder of the executable.
    - Else, use the folder of this module.
"""
def _app_base_dir() -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

"""Ensure app-relative session_logs directory exists and return its path."""
def ensure_session_dir() -> str:
    base = _app_base_dir()
    path = os.path.join(base, "session_logs")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        print(f"Warning: Failed to create session_logs directory: {e}", file=sys.stderr)
    return path

"""Return a *unique* file name per login: SESSION_<YYYYMMDD>_<HHMMSS>_<USER>.log"""
def session_filename(user: str) -> str:
    ts_date = time.strftime("%Y%m%d")
    ts_time = time.strftime("%H%M%S")
    safe_user = (user or "unknown").replace(" ", "_")
    return f"SESSION_{ts_date}_{ts_time}_{safe_user}.log"

"""Asynchronous session logger backed by a background writer thread."""
class SessionLogger:

    """Sets the user, builds path, starts the daemon writer thread, and enqueues a session header with timestamp."""
    def __init__(self, user: str) -> None:
        self.user = user or "unknown"
        folder = ensure_session_dir()
        self.path = os.path.join(folder, session_filename(self.user))

        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()

        # enqueue session header
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._queue.put(("data", f"\n=== Session started by {self.user} at {ts} ===\n------------------------------------------------------------\n"))
        except Exception as e:
            print(f"Warning: Failed to enqueue session header: {e}", file=sys.stderr)

    """Enqueues a single timestamped line; ignores empty input; warns on enqueue errors."""
    def append(self, line: str) -> None:
        if not line:
            return
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._queue.put(("data", f"[{ts}] {line}\n"))
        except Exception as e:
            print(f"Warning: Failed to enqueue line to session log: {e}", file=sys.stderr)

    """Enqueues a titled, timestamped block followed by a separator line; warns on enqueue errors."""
    def append_block(self, title: str, text: str) -> None:
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            header = f"\n---- {title} ({ts}) ----\n" if title else f"\n---- ({ts}) ----\n"
            body = (text or "") + "\n------------------------------------------------------------\n"
            self._queue.put(("data", header + body))
        except Exception as e:
            print(f"Warning: Failed to enqueue block to session log: {e}", file=sys.stderr)

    """Enqueues a titled, timestamped JSON dump (ensure_ascii=False) followed by a separator; warns on enqueue errors."""
    def append_json(self, title: str, obj) -> None:
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            header = f"\n---- {title} ({ts}) ----\n" if title else f"\n---- ({ts}) ----\n"
            payload = json.dumps(obj, ensure_ascii=False) + "\n------------------------------------------------------------\n"
            self._queue.put(("data", header + payload))
        except Exception as e:
            print(f"Warning: Failed to enqueue JSON to session log: {e}", file=sys.stderr)

    """Signals stop, enqueues a sentinel, and joins the writer thread (bounded by timeout)."""
    def close(self, timeout: float = 5.0) -> None:
        try:
            self._stop_event.set()
            # put a sentinel
            self._queue.put(("_stop", ""))
            self._thread.join(timeout)
        except Exception:
            pass

    """Continuously drains the queue, appending entries to the UTF‑8 log file; stops on sentinel or when signaled and queue is empty."""
    def _writer_loop(self) -> None:
        try:
            while not self._stop_event.is_set() or not self._queue.empty():
                try:
                    item = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                try:
                    kind, data = item
                    if kind == "_stop":
                        break
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(data)
                except Exception as e:
                    print(f"Warning: Failed to write session log entry: {e}", file=sys.stderr)
                finally:
                    try:
                        self._queue.task_done()
                    except Exception:
                        pass
        except Exception as e:
            print(f"SessionLogger background thread crashed: {e}", file=sys.stderr)
