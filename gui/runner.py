import os
import runpy
import signal
import subprocess
import sys
import threading
import time
from typing import Callable

from gui.paths import ROOT

# Session and flash runs are child processes of the app itself (`--run` / `--module`), which
# also works inside a packaged app where no separate python executable exists.


def child(argv: list[str]) -> None:
    """Runs in the child: an entry point script or a module, as `python -u` would."""
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    mode, target, *args = argv
    if mode == "--run":
        path = os.path.join(ROOT, target)
        sys.argv = [path, *args]
        sys.path.insert(0, os.path.dirname(path))
        runpy.run_path(path, run_name="__main__")
    else:
        sys.argv = [target, *args]
        runpy.run_module(target, run_name="__main__", alter_sys=True)


def command(*argv: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *argv]
    return [sys.executable, "-u", os.path.join(ROOT, "gui", "main.py"), *argv]


class Process:
    def __init__(self, argv: list[str], cwd: str, env: dict, on_line: Callable[[str], None],
                 on_exit: Callable[[int], None]):
        self.on_line, self.on_exit = on_line, on_exit
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.proc = subprocess.Popen(command(*argv), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", bufsize=1,
                                     creationflags=flags)
        self.started = time.monotonic()
        threading.Thread(target=self._pump, daemon=True).start()

    @property
    def running(self) -> bool:
        return self.proc.poll() is None

    def _pump(self) -> None:
        for line in self.proc.stdout:
            self.on_line(line.rstrip("\n"))
        self.on_exit(self.proc.wait())

    def stop(self) -> None:
        # An interrupt lets the entry point leave the network and close the board; a launcher
        # that ignores it for 15 s is terminated.
        if not self.running:
            return
        self.proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        threading.Thread(target=self._escalate, daemon=True).start()

    def _escalate(self) -> None:
        for action, wait in ((None, 15), (self.proc.terminate, 5), (self.proc.kill, 0)):
            if action:
                action()
            try:
                self.proc.wait(wait or None)
                return
            except subprocess.TimeoutExpired:
                continue


def base_env(settings, port: str, trace: str | None = None) -> dict:
    env = dict(os.environ, PYTHONUNBUFFERED="1", POKELDN_ESP32_BAUD=str(settings.baud))
    env["POKELDN_RADIO"] = f"esp32:{port or 'auto'}"
    if trace:
        env["POKELDN_ESP32_TRACE"] = trace
    return env
