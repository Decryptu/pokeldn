"""The Pokemon files a run saved in the Received folder. Every tool's output path carries the run's
{stamp} (pokeldn.app.catalog); a launcher adds a suffix per trade, or writes into a folder so named."""
import os
import re

POKEMON = re.compile(r"\.(pk3|ek3|pb7|pk8|pb8|pa8|pk9|pa9)$", re.IGNORECASE)


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
