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


_closing: list[Callable[[], None]] = []


def at_app_close(hook: Callable[[], None]) -> None:
    """Runs `hook` in the child when the app closes its stdin, before the KeyboardInterrupt: for a child whose
    main thread the interrupt does not leave (pokeldn.pad.service)."""
    _closing.append(hook)


def _read_the_app() -> None:
    # The app answers the child's pop-ups on its stdin (pokeldn.popup) and stops a managed run by closing it; the
    # close raises the same KeyboardInterrupt as Ctrl-C, which a windowless child on Windows cannot receive as a
    # signal.
    from pokeldn import popup
    for line in sys.stdin:
        popup.receive(line)
    for hook in list(_closing):
        hook()
    if os.environ.get("POKELDN_MANAGED_RUN"):
        _thread.interrupt_main()


def child(argv: list[str]) -> None:
    """Runs in the child: an entry point script or a module, as `python -u` would."""
    for stream in (sys.stdout, sys.stderr):
        if stream:
            stream.reconfigure(encoding="utf-8", line_buffering=True)
    if sys.stdin and (os.environ.get("POKELDN_MANAGED_RUN") or os.environ.get("POKELDN_POPUPS")):
        threading.Thread(target=_read_the_app, daemon=True).start()
    _execute(argv)


def _execute(argv: list[str]) -> None:
    mode, target, *args = argv
    if mode == "--run":
        path = os.path.join(ROOT, target)
        if os.path.isabs(target):     # a plugin's script: loading the plugins puts it under their guardrails
            from pokeldn import plugins
            plugins.load()
        sys.argv = [path, *args]
        sys.path.insert(0, os.path.dirname(path))
        if os.environ.get("POKELDN_PLATFORM") == "android" and target.startswith("bin/"):
            # Chaquopy ships the launchers compiled, with no source file runpy could run (examples/android).
            module = "bin." + os.path.splitext(os.path.basename(target))[0]
            sys.modules.pop(module, None)   # imported once to read its flags (introspect)
            runpy.run_module(module, run_name="__main__", alter_sys=True)
            return
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
    """A child of the app. With `popups` (pokeldn.app.popups.Manager), the child's `[popup]` lines open pop-ups
    under `label`, never reaching `on_line`, and their answers go back on its stdin (pokeldn.popup)."""

    def __init__(self, argv: list[str], cwd: str, env: dict, on_line: Callable[[str], None],
                 on_exit: Callable[[int], None], bluetooth: bool = False, popups=None, label: str = ""):
        self.on_line, self.on_exit = on_line, on_exit
        self.stdin_lock = threading.Lock()
        if popups is not None:
            env = dict(env, POKELDN_POPUPS="1")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.proc = subprocess.Popen(command(*argv, bluetooth=bluetooth), cwd=cwd, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", bufsize=1,
                                     creationflags=flags)
        self.started = time.monotonic()
        self.popups = popups.program(label, self.send) if popups is not None else None
        threading.Thread(target=self._pump, daemon=True).start()

    @property
    def running(self) -> bool:
        return self.proc.poll() is None

    def _take(self, line: str) -> None:
        from pokeldn import popup
        before, message = popup.read(line) if self.popups is not None else (line, None)
        if message is None:
            self.on_line(line)
            return
        if before.strip():
            self.on_line(before)
        self.popups.take(message)

    def _pump(self) -> None:
        for line in self.proc.stdout:
            self._take(line.rstrip("\n"))
        self.proc.stdout.close()
        with self.stdin_lock:
            if not self.proc.stdin.closed:
                self.proc.stdin.close()
        if self.popups is not None:
            self.popups.ended()
        self.on_exit(self.proc.wait())

    def send(self, message: dict) -> None:
        """Answers one of the child's pop-ups on its stdin; a child that has stopped reading gets nothing."""
        from pokeldn import popup
        with self.stdin_lock:
            try:
                self.proc.stdin.write(popup.line(message) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                pass

    def stop(self) -> None:
        # An interrupt lets the entry point leave the network and close the board; a launcher
        # that ignores it for 15 s is terminated.
        if not self.running:
            return
        with self.stdin_lock:
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


class InProcess(Process):
    """A run on this interpreter's own thread, where no second interpreter can start (Android, docs/gui.md).
    One at a time: it holds the process's stdout, argv, environment and working directory while it runs."""

    current: "InProcess | None" = None

    def __init__(self, argv: list[str], cwd: str, env: dict, on_line: Callable[[str], None],
                 on_exit: Callable[[int], None], bluetooth: bool = False, popups=None, label: str = ""):
        if InProcess.current is not None:
            raise RuntimeError("A run is already in progress.")
        self.on_line, self.on_exit = on_line, on_exit
        self.code: int | None = None
        self.stopping = False
        self.started = time.monotonic()
        if popups is not None:
            env = dict(env, POKELDN_POPUPS="1")
        self.popups = popups.program(label, self.send) if popups is not None else None
        InProcess.current = self
        self.thread = threading.Thread(target=self._main, args=(argv, cwd, env), name="pokeldn-run", daemon=True)
        self.thread.start()

    @property
    def running(self) -> bool:
        return self.code is None

    def _main(self, argv, cwd, env) -> None:
        import traceback
        saved = dict(os.environ), os.getcwd(), list(sys.argv), list(sys.path), sys.stdout, sys.stderr
        lines = _Lines(self._take)
        code = 0
        try:
            os.environ.clear()
            os.environ.update(env)
            os.chdir(cwd)
            sys.stdout = sys.stderr = lines
            for hook in _before_run:
                hook()
            _execute(argv)
        except SystemExit as error:
            if isinstance(error.code, int) or error.code is None:
                code = error.code or 0
            else:
                lines.write(f"{error.code}\n")
                code = 1
        except KeyboardInterrupt:
            code = 0 if self.stopping else 130
        except BaseException:
            lines.write(traceback.format_exc())
            code = 1
        finally:
            lines.flush()
            environ, cwd, sys.argv[:], sys.path[:], sys.stdout, sys.stderr = saved
            os.environ.clear()
            os.environ.update(environ)
            os.chdir(cwd)
            for hook in _after_run:
                try:
                    hook()
                except Exception:   # cleanup never hides the run's own exit code
                    pass
            InProcess.current = None
            self.code = code
            if self.popups is not None:
                self.popups.ended()
            self.on_exit(code)

    def send(self, message: dict) -> None:
        from pokeldn import popup
        if self.running:
            popup.receive(popup.line(message))

    def stop(self) -> None:
        """The KeyboardInterrupt a closed stdin raises in a child, raised in the run's thread instead."""
        import ctypes
        if not self.running:
            return
        self.stopping = True
        for hook in list(_closing):
            hook()
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(self.thread.ident), ctypes.py_object(KeyboardInterrupt))


class _Lines:
    """A run's stdout and stderr, cut into lines for the session panel."""

    encoding = "utf-8"

    def __init__(self, take: Callable[[str], None]):
        self.take, self.partial, self.lock = take, "", threading.Lock()

    def write(self, text: str) -> int:
        with self.lock:
            *done, self.partial = (self.partial + text).split("\n")
        for line in done:
            self.take(line)
        return len(text)

    def flush(self) -> None:
        with self.lock:
            rest, self.partial = self.partial, ""
        if rest:
            self.take(rest)

    def isatty(self) -> bool:
        return False

    def reconfigure(self, **_) -> None:
        pass


_before_run: list[Callable[[], None]] = []
_after_run: list[Callable[[], None]] = []


def before_run(hook: Callable[[], None]) -> None:
    """Runs `hook` on the run's thread before each in-process run starts."""
    _before_run.append(hook)


def after_run(hook: Callable[[], None]) -> None:
    """Runs `hook` after each in-process run: state a child process would have taken with it (the radio)."""
    _after_run.append(hook)


if os.environ.get("POKELDN_PLATFORM") in ("android", "ios"):   # neither starts a second Python
    Process = InProcess   # noqa: F811


def base_env(settings, port: str, trace: str | None = None) -> dict:
    env = dict(os.environ, PYTHONUNBUFFERED="1", POKELDN_ESP32_BAUD=str(settings.baud),
               POKELDN_MANAGED_RUN="1", POKELDN_HOME_TRACKER=settings.home_tracker)
    env["POKELDN_RADIO"] = f"{settings.radio}:" if settings.radio else f"esp32:{port or 'auto'}"
    if trace:
        env["POKELDN_ESP32_TRACE"] = trace
    return env
