import _thread
import os
import runpy
import subprocess
import sys
import threading
import time
from typing import Callable

from pokeldn.app.paths import ROOT

# Session and flash runs are child processes of the app itself (`--run` / `--module`), which
# also works inside a packaged app where no separate python executable exists.


def _stop_on_stdin_close() -> None:
    # The app stops a run by closing its stdin; this raises the same KeyboardInterrupt as Ctrl-C,
    # which a windowless child on Windows cannot receive as a signal.
    sys.stdin.read()
    _thread.interrupt_main()


def child(argv: list[str]) -> None:
    """Runs in the child: an entry point script or a module, as `python -u` would."""
    for stream in (sys.stdout, sys.stderr):
        if stream:
            stream.reconfigure(encoding="utf-8", line_buffering=True)
    if sys.stdin and os.environ.get("POKELDN_MANAGED_RUN"):
        threading.Thread(target=_stop_on_stdin_close, daemon=True).start()
    mode, target, *args = argv
    if mode == "--run":
        path = os.path.join(ROOT, target)
        sys.argv = [path, *args]
        sys.path.insert(0, os.path.dirname(path))
        runpy.run_path(path, run_name="__main__")
    else:
        sys.argv = [target, *args]
        runpy.run_module(target, run_name="__main__", alter_sys=True)


# macOS 26 delivers no Bluetooth LE discoveries to a background process signed as an app's main
# executable; this bare-signed copy of it gets an active scan (scripts/pack_app.py, docs/gui.md).
BLUETOOTH_HELPER = os.path.join(os.path.dirname(os.path.dirname(sys.executable)), "Helpers", "pokeldn-bluetooth")


def command(*argv: str, bluetooth: bool = False) -> list[str]:
    if getattr(sys, "frozen", False):
        if bluetooth and sys.platform == "darwin" and os.path.isfile(BLUETOOTH_HELPER):
            return [BLUETOOTH_HELPER, *argv]
        return [sys.executable, *argv]
    return [sys.executable, "-u", os.path.join(ROOT, "pokeldn", "app", "entry.py"), *argv]


class Process:
    def __init__(self, argv: list[str], cwd: str, env: dict, on_line: Callable[[str], None],
                 on_exit: Callable[[int], None], bluetooth: bool = False):
        self.on_line, self.on_exit = on_line, on_exit
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.proc = subprocess.Popen(command(*argv, bluetooth=bluetooth), cwd=cwd, env=env, stdin=subprocess.PIPE,
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
        self.proc.stdout.close()
        if not self.proc.stdin.closed:
            self.proc.stdin.close()
        self.on_exit(self.proc.wait())

    def stop(self) -> None:
        # An interrupt lets the entry point leave the network and close the board; a launcher
        # that ignores it for 15 s is terminated.
        if not self.running:
            return
        try:
            self.proc.stdin.close()
        except OSError:
            pass
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
    env = dict(os.environ, PYTHONUNBUFFERED="1", POKELDN_ESP32_BAUD=str(settings.baud),
               POKELDN_MANAGED_RUN="1")
    env["POKELDN_RADIO"] = f"esp32:{port or 'auto'}"
    if trace:
        env["POKELDN_ESP32_TRACE"] = trace
    return env
