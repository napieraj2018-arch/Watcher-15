"""Supervise app and X display; never report a healthy API without Xvfb.
No credentials, browser data or environment values are written to logs.
"""
from __future__ import annotations
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


def display_ready(number: int) -> bool:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(0.3)
    try:
        client.connect(f"/tmp/.X11-unix/X{number}")
        return True
    except OSError:
        return False
    finally:
        client.close()


def terminate(process: subprocess.Popen | None, timeout: float = 12.0) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main(command: list[str] | None = None) -> int:
    children: list[subprocess.Popen] = []
    stopping = False

    def on_signal(_number, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    number = next((n for n in range(99, 130)
                   if not Path(f"/tmp/.X11-unix/X{n}").exists()
                   and not Path(f"/tmp/.X{n}-lock").exists()), None)
    if number is None:
        print("AI_BROWSER_DISPLAY_START_FAILED: no free local display", flush=True)
        return 1
    env = os.environ.copy()
    env["DISPLAY"] = f":{number}"
    try:
        display = subprocess.Popen(["Xvfb", f":{number}", "-screen", "0",
                                    "1280x800x24", "-nolisten", "tcp", "-noreset"],
                                   stdout=subprocess.DEVNULL, stderr=sys.stderr, env=env)
        children.append(display)
        deadline = time.monotonic() + 15
        while not display_ready(number):
            if stopping or display.poll() is not None or time.monotonic() > deadline:
                print("AI_BROWSER_DISPLAY_START_FAILED", flush=True)
                return 1
            time.sleep(0.1)
        print("AI_BROWSER_DISPLAY_READY: supervised", flush=True)
        app = subprocess.Popen(command or [sys.executable, "/app/bootstrap.py"], env=env)
        children.append(app)
        while not stopping:
            if display.poll() is not None:
                print("AI_BROWSER_DISPLAY_EXITED: stopping app for clean restart", flush=True)
                return 1
            if app.poll() is not None:
                return app.returncode
            time.sleep(0.3)
        return 0
    finally:
        for process in reversed(children):
            terminate(process)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
