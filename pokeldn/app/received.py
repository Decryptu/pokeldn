"""The Pokemon files a run saved in the Received folder. Every tool's output path carries the run's
{stamp} (pokeldn.app.catalog); a launcher adds a suffix per trade, or writes into a folder so named."""
import os
import re

POKEMON = re.compile(r"\.(pk3|ek3|pb7|pk8|pb8|pa8|pk9|pa9)$", re.IGNORECASE)
DONE = re.compile(r"^\[done\] trade (\d+) complete$")   # pokeldn.ldn.show_done


# pokeldn.frlg.gift.host_mg_app.SaveTransferHostApplication._progress
SAVE_PROGRESS = re.compile(r"^\[save\] (backup|restore) (\d+) of (\d+) (KB|sectors)$")


def save_progress(line: str) -> tuple[str, int, int] | None:
    """(backup or restore, done, total) from a save transfer's progress line, or None."""
    match = SAVE_PROGRESS.match(line.strip())
    return (match.group(1), int(match.group(2)), int(match.group(3))) if match else None


def trades_done(line: str) -> int | None:
    """The run's completed-trade count a log line reports, or None."""
    match = DONE.match(line.strip())
    return int(match.group(1)) if match else None


def session_files(folder: str, stamp: str) -> list[str]:
    """The run's Pokemon files, oldest first."""
    found = []
    try:
        entries = list(os.scandir(os.path.expanduser(folder)))
    except OSError:
        return []
    for entry in entries:
        if stamp not in entry.name:
            continue
        try:
            if entry.is_dir():
                found += [inner.path for inner in os.scandir(entry.path)
                          if inner.is_file() and POKEMON.search(inner.name)]
            elif entry.is_file() and POKEMON.search(entry.name):
                found.append(entry.path)
        except OSError:
            continue

    def written(path: str) -> tuple[float, str]:
        try:
            return os.path.getmtime(path), path
        except OSError:
            return 0.0, path
    return sorted(found, key=written)
