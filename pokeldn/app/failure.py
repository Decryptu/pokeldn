"""Why a run ended without doing its job, in one sentence a player can act on (docs/gui.md, When a run fails).
`Watch` reads the run's lines as they come; `verdict` names the cause once it has exited."""
import re
from dataclasses import dataclass

from pokeldn.app.i18n import t as tr
from pokeldn.ldn import LINK_PREFIX

DONE = re.compile(r"^\[done\] \w+ \d+ complete")


@dataclass(frozen=True)
class Failure:
    text: str
    action: str = ""     # board, settings, copy or "" (the console steps are already on the panel)
    retry: bool = False  # starting again may get past it (Settings, Retry failed trades)


def _board_dropped():
    return Failure(tr('failure.board_dropped', "The board's USB connection dropped. Unplug it, plug it back in "
                      "and start again; if it keeps happening, try another cable or USB port."), "board", retry=True)


def _port_busy():
    return Failure(tr('failure.port_busy', "The board's port is in use. Close any other program using it, "
                      "such as a second pokeldn window or a serial monitor, then start again."), "board")


def _old_firmware():
    return Failure(tr('failure.old_firmware', "The board's firmware does not match this app. Install the "
                      "firmware again from the Board page."), "board")


def _no_answer():
    return Failure(tr('failure.board_silent', "The board did not answer. Install pokeldn's firmware from the "
                      "Board page, or unplug the board and plug it back in."), "board")


def _keys(line: str):
    name = line.split("prod.keys has no ", 1)[1].split(";", 1)[0].strip()
    return Failure(tr('failure.keys_missing', "Your prod.keys has no {value0}. Choose a prod.keys dumped from "
                      "your console in Settings.", value0=name), "settings")


def _join():
    return Failure(tr('failure.join_failed', "The board could not join the console's network. Keep the board "
                      "close to the console and start again."), retry=True)


# (pattern, cause): the first line of a run that matches names the cause; later matches never replace it.
CAUSES = (
    (re.compile(r"\[esp32\] The board's USB connection failed|the board left USB"), lambda line: _board_dropped()),
    (re.compile(r"Resource busy|Access is denied|PermissionError: \[Errno 13\]|could not exclusively lock"),
     lambda line: _port_busy()),
    (re.compile(r"board speaks protocol \d+, host speaks"), lambda line: _old_firmware()),
    (re.compile(r"RadioError: no reply 0x[0-9a-f]+ to command 0x01\b|FileNotFoundError: .*(/dev/|COM\d)"),
     lambda line: _no_answer()),
    (re.compile(r"prod\.keys has no "), _keys),
    (re.compile(r"the board could not join"), lambda line: _join()),
)


class Watch:
    """The facts `verdict` needs, read from one run's lines."""

    def __init__(self, linking: bool):
        self.linking = linking      # the run's radio prints `[link]` lines: the board, and a console that joins
        self.cause: Failure | None = None
        self.waited = False         # the radio hosted or scanned for a console (pokeldn.ldn.show_link)
        self.linked = False         # a console joined at some point
        self.present = False        # a console is joined now
        self.done = 0
        self.traceback = False

    def line(self, line: str) -> None:
        if line.startswith(LINK_PREFIX):
            state = line[len(LINK_PREFIX):].strip()
            self.waited = self.waited or state == "waiting"
            if state in ("joined", "left"):
                self.present = state == "joined"
                self.linked = self.linked or self.present
            return
        if DONE.match(line):
            self.done += 1
        if line.startswith("Traceback (most recent call last)"):
            self.traceback = True
        if self.cause is None:
            for pattern, cause in CAUSES:
                if pattern.search(line):
                    self.cause = cause(line)
                    return

    def verdict(self, code: int, stopped: bool) -> Failure | None:
        """None for a run that did its job, or one the player stopped after it did."""
        if self.cause is not None:
            return self.cause
        if stopped or self.done:
            return None
        if self.linking and self.waited and not self.linked:
            return Failure(tr('failure.no_console', "The console never joined. Check that it is on the screen "
                              "the console steps name, then start again."), retry=True)
        if code and self.traceback:
            return Failure(tr('failure.unexpected', "The run stopped on an error pokeldn did not expect. Copy the "
                              "log and send it with a bug report."), "copy")
        return None
