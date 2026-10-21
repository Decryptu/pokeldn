"""What the Games page keeps of a plugin's `[panel]` lines (pokeldn.panel) and its library's sort order: one
JSON file per plugin, kept after its runs and deleted with the plugin (plugin_store.remove)."""
import json
import os
from pathlib import Path

from pokeldn import panel, plugins
from pokeldn.app import library, paths


def _folder() -> Path:
    return paths.DATA / "plugin-panels"


def _path(plugin_id: str) -> Path:
    return _folder() / f"{plugin_id}.json"


def load(plugin_id: str) -> dict:
    try:
        data = json.loads(_path(plugin_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    cards, notes = data.get("cards"), data.get("notes")
    return {"cards": cards if isinstance(cards, dict) else {}, "notes": notes if isinstance(notes, dict) else {},
            "sort": data.get("sort") if data.get("sort") in library.SORTS else None}


def _save(plugin_id: str, data: dict) -> None:
    _folder().mkdir(parents=True, exist_ok=True)
    temp = _path(plugin_id).with_suffix(".part")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, _path(plugin_id))


def apply(plugin_id: str, message: dict) -> bool:
    """Keeps a card or a note `panel.read` returned, or drops a cleared one; False when nothing changed
    or the plugin already holds panel.CARDS other cards."""
    data = load(plugin_id)
    store, key = (data["cards"], message["id"]) if "id" in message else (data["notes"], message["file"])
    if message.get("clear"):
        if store.pop(key, None) is None:
            return False
    else:
        if store is data["cards"] and key not in store and len(store) >= panel.CARDS:
            return False
        if store.get(key) == message:
            return False
        store[key] = message
    _save(plugin_id, data)
    return True


def set_sort(plugin_id: str, sort: str) -> None:
    if sort not in library.SORTS:
        raise ValueError(f"a library sort is one of {', '.join(library.SORTS)}")
    data = load(plugin_id)
    data["sort"] = sort
    _save(plugin_id, data)


def sort(plugin: plugins.Plugin) -> str:
    """The player's choice, else plugin.toml's `library_sort`, else newest first."""
    return load(plugin.id)["sort"] or plugin.library_sort or library.DEFAULT_SORT


def forget(plugin_id: str) -> None:
    _path(plugin_id).unlink(missing_ok=True)


def image(plugin: plugins.Plugin, value) -> str | None:
    """A card's or note's image as a file the app may show: a PNG or JPEG of at most panel.IMAGE_BYTES in the
    plugin's data folder or library; None otherwise."""
    if not value:
        return None
    path = Path(value).expanduser()
    try:
        path = path.resolve(strict=True)
        roots = [plugins.data_folder(plugin.id).resolve()]
        if plugin.library:
            roots.append(plugins.library_path(plugin.library).resolve())
        if not any(path.is_relative_to(root) for root in roots) or path.stat().st_size > panel.IMAGE_BYTES:
            return None
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return None
    return str(path) if head.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")) else None
