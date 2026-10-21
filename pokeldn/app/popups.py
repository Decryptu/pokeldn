"""The app's side of the pop-ups programs show (pokeldn.popup, docs/gui.md, Pop-ups): which ones show and where
each answer goes.

The manager runs on the app's UI loop: `call` brings each program's messages there, and the view (gui.popups)
shows and hides the pop-ups and reports the buttons pressed.
"""

from pokeldn.popup import ANSWERS, CHOICES, LIMIT, TONES

# What a pop-up shows is the program's to say, up to these lengths.
CLIP = {"title": 120, "text": 4000, "label": 40, "agree": 40, "disagree": 40, "option": 60}


def _clip(value, length: int) -> str:
    value = str(value or "")
    return value if len(value) <= length else value[:length - 1] + "…"


class Entry:
    """One pop-up as the app shows it."""

    def __init__(self, program: "Program", message: dict):
        kind, n = message.get("kind"), message.get("n")
        if kind not in ANSWERS or type(n) is not int:
            raise ValueError("not a pop-up")
        self.program, self.id, self.n, self.kind = program, str(message.get("id") or ""), n, kind
        self.title = _clip(message.get("title"), CLIP["title"])
        self.text = _clip(message.get("text"), CLIP["text"])
        self.label = _clip(message.get("label"), CLIP["label"]) or "OK"
        self.agree = _clip(message.get("agree"), CLIP["agree"])
        self.disagree = _clip(message.get("disagree"), CLIP["disagree"])
        options = message.get("options") if kind == "choose" else []
        if not isinstance(options, list) or kind == "choose" and not 2 <= len(options) <= CHOICES:
            raise ValueError("not a pop-up")
        self.options = [_clip(o, CLIP["option"]) for o in options]
        if not self.id or kind == "confirm" and not (self.agree and self.disagree) or not all(self.options):
            raise ValueError("not a pop-up")
        self.tone = message.get("tone") if message.get("tone") in TONES else "info"

    @property
    def source(self) -> str:
        """The program that opened it, which its header names; empty for the app's own."""
        return self.program.label

    @property
    def answers(self) -> tuple[str, ...]:
        return tuple(str(i) for i in range(len(self.options))) + ANSWERS[self.kind]

    def press(self, answer: str) -> None:
        """The view: the player pressed `answer`'s button."""
        self.program.manager.answer(self, answer)

    def escaped(self) -> None:
        """The view: the pop-up closed, by Esc, a click outside, or the app."""
        self.program.manager.dismissed(self)


class Program:
    """One program's pop-ups: a run the app started, or the app's own code. Its ids are its own."""

    def __init__(self, manager: "Manager", label: str, send):
        self.manager, self.label, self.send, self.over = manager, label, send, False

    def take(self, message: dict) -> None:
        """A message the program sent, from any thread."""
        self.manager.call(lambda: self.manager.take(self, message))

    def ended(self) -> None:
        """The program exited, from any thread: its confirmations and choices close, and its acknowledgements
        stay with no answer to go back."""
        self.manager.call(lambda: self.manager.ended(self))


class Manager:
    def __init__(self, view, call=lambda fn: fn()):
        self.view, self.call = view, call
        self.open: list[Entry] = []      # bottom to top

    def program(self, label: str, send) -> Program:
        """A program to show pop-ups for: `send(message)` takes the answers back to it."""
        return Program(self, label, send)

    def _find(self, program, id) -> Entry | None:
        return next((e for e in self.open if e.program is program and e.id == id), None)

    def take(self, program: Program, message: dict) -> None:
        if program.over or not isinstance(message, dict):
            return
        old = self._find(program, str(message.get("id") or ""))
        if message.get("op") == "cancel":
            if old is not None:
                self._close(old)
        elif message.get("op") == "open":
            try:
                entry = Entry(program, message)
            except ValueError:
                return
            if old is not None:     # in place: it keeps its dialog and its place in the stack
                self.open[self.open.index(old)] = entry
                self.view.refresh(old, entry)
            elif sum(e.program is program for e in self.open) < LIMIT:
                self.open.append(entry)
                self.view.show(entry)

    def _close(self, entry: Entry) -> None:
        if entry in self.open:
            self.open.remove(entry)
            self.view.hide(entry)

    def answer(self, entry: Entry, answer: str) -> None:
        """The player answered an open pop-up: it closes and the answer goes back to its program."""
        if entry not in self.open or answer not in entry.answers:
            return
        self._close(entry)
        if not entry.program.over:
            entry.program.send({"id": entry.id, "n": entry.n, "answer": answer})

    def dismissed(self, entry: Entry) -> None:
        """A pop-up's dialog closed: Esc or a click outside, unless the app closed it first. A confirmation or a
        choice is dismissed, an acknowledgement acknowledged."""
        if entry in self.open:
            self.answer(entry, "ack" if entry.kind == "ack" else "dismiss")

    def ended(self, program: Program) -> None:
        program.over = True
        for entry in [e for e in self.open if e.program is program and e.kind != "ack"]:
            self._close(entry)
