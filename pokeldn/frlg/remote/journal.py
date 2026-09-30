"""Asynchronous JSONL journal for data-free P0 diagnostics."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import re
import threading

from pokeldn.app.paths import DATA


JOURNAL_QUEUE_CAPACITY = 128


class JournalError(RuntimeError):
    pass


class RemoteJournal:
    """Store phase names, state and digests only; never persist blocks or room keys."""

    def __init__(self, run_id, *, root=None):
        if (not isinstance(run_id, str) or len(run_id) != 32
                or re.fullmatch(r"[0-9a-fA-F]{32}", run_id) is None):
            raise ValueError("run_id must be a 128-bit hex identifier")
        self.run_id = run_id
        self.directory = Path(root or DATA) / "remote" / run_id
        self.path = self.directory / "events.jsonl"
        self._queue = queue.Queue(maxsize=JOURNAL_QUEUE_CAPACITY)
        self._failure = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._writer, name="frlg-remote-journal", daemon=True)
        self._thread.start()

    @property
    def failure(self):
        return self._failure

    def append(self, event, **fields):
        if self._closed:
            raise JournalError("journal is closed")
        if not isinstance(event, str) or not event or len(event) > 80:
            raise ValueError("journal event must be a short non-empty string")
        if any(name in fields for name in ("data", "room_key", "pokemon", "pokemon_bytes")):
            raise ValueError("journal cannot store game blocks, room keys or Pokemon data")
        record = {"time": datetime.now(timezone.utc).isoformat(),
                  "run_id": self.run_id, "event": event, **fields}
        try:
            encoded = json.dumps(record, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("journal fields must be JSON-safe scalar diagnostics") from exc
        try:
            self._queue.put_nowait(encoded)
        except queue.Full as exc:
            raise JournalError("journal queue is full; stop the probe cleanly") from exc
        if self._failure is not None:
            raise JournalError(self._failure)

    def _writer(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                while True:
                    item = self._queue.get()
                    if item is None:
                        break
                    stream.write(item + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
        except OSError as exc:
            self._failure = f"journal write failed: {exc}"

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.put(None, timeout=2.0)
        except queue.Full as exc:
            self._failure = "journal could not drain before close"
            raise JournalError(self._failure) from exc
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            self._failure = "journal writer did not stop"
            raise JournalError(self._failure)
        if self._failure is not None:
            raise JournalError(self._failure)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
