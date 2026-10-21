"""Bounds and portable paths for downloaded archives."""
import re
import struct
import zipfile
from pathlib import Path, PurePosixPath


def open_zip(path, max_files: int):
    """Count directory entries before Python allocates the ZIP's complete file index."""
    with open(path, "rb") as source:
        end = zipfile._EndRecData(source)
        if end is None:
            raise OSError("the archive has no ZIP directory")
        size = end[zipfile._ECD_SIZE]
        start = end[zipfile._ECD_LOCATION] - size
        if start < 0 or size > min(32 << 20, max_files * 1024):
            raise OSError("the archive directory is too large")
        source.seek(start)
        count, used = 0, 0
        while used < size:
            header = source.read(46)
            if len(header) != 46 or header[:4] != b"PK\x01\x02":
                raise OSError("the archive directory is damaged")
            names, extra, comment = struct.unpack_from("<HHH", header, 28)
            count += 1
            used += 46 + names + extra + comment
            if count > max_files or names > 1024 or used > size:
                raise OSError("the archive holds too many files or an oversized path")
            source.seek(names + extra + comment, 1)
    return zipfile.ZipFile(path)


def relative(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or name.startswith("/"):
        raise OSError("the archive holds an unsafe path")
    parts = name.split("/")
    if any(p == ".." or any(ord(c) < 32 or c in ':<>"|?*' for c in p)
           or (p not in ("", ".") and (p.endswith((" ", ".")) or
               re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", p))) for p in parts):
        raise OSError("the archive holds an unsafe path")
    return str(PurePosixPath(name))


def destination(folder: Path, name: str) -> Path:
    out = folder / relative(name)
    if not out.resolve().is_relative_to(folder.resolve()):
        raise OSError("the archive path escapes its folder")
    return out


def bounded(members, max_files: int, max_bytes: int, max_file: int):
    total, seen, kept = 0, set(), []
    for name, size, member in members:
        clean = relative(name)
        folded = clean.casefold()
        if folded in seen or size < 0 or size > max_file:
            raise OSError("the archive holds a duplicate path or an oversized file")
        seen.add(folded)
        total += size
        if len(seen) > max_files or total > max_bytes:
            raise OSError("the unpacked archive is too large")
        kept.append(member)
    return kept


def copy(source, target, limit: int):
    done = 0
    while chunk := source.read(min(65536, limit - done + 1)):
        done += len(chunk)
        if done > limit:
            raise OSError("the unpacked file is too large")
        target.write(chunk)
