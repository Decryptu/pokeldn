"""Files dragged from the desktop onto the app.

Flet's own client takes no file drops; scripts/build_client.py builds one with gui/flet_drop, and
`FileDrop` is that extension's control. Under any other client `target` leaves the content as it is.
"""
import os
import sys
from pathlib import Path
from typing import Callable, Optional

import flet as ft

from gui import theme as t
from gui.flet_client import view_path


def use_client() -> bool:
    """Points Flet at the built client; a frozen app carries it inside (scripts/pack_app.py)."""
    global AVAILABLE
    if os.environ.get("POKELDN_GUI_WEB"):
        AVAILABLE = False
    elif getattr(sys, "frozen", False):
        AVAILABLE = True
    elif (path := view_path()) is not None:
        os.environ["FLET_VIEW_PATH"] = str(path)
        AVAILABLE = True
    return AVAILABLE


AVAILABLE = False


@ft.control("FileDrop")
class FileDrop(ft.LayoutControl):
    content: Optional[ft.Control] = None
    on_drop: Optional[ft.ControlEventHandler["FileDrop"]] = None
    on_enter: Optional[ft.ControlEventHandler["FileDrop"]] = None
    on_leave: Optional[ft.ControlEventHandler["FileDrop"]] = None


def outline(radius: float) -> ft.BoxDecoration:
    return ft.BoxDecoration(border=ft.Border.all(1.5, t.BLUE), border_radius=radius,
                            bgcolor=ft.Colors.with_opacity(0.08, t.BLUE))


def target(content: ft.Control, on_files: Callable[[list[str]], None],
           glow: ft.Container | Callable[[], ft.Container | None] | None = None, **kwargs) -> ft.Control:
    """`content` takes dropped files: `on_files(paths)`. While files hover, `glow` (a Container, one returned
    by a callable, by default `content`) is outlined in blue; the outline is drawn over it and moves nothing."""
    if not AVAILABLE:
        return content
    lit_now: list[ft.Container] = []

    def lit(on: bool) -> None:
        for box in lit_now:
            box.foreground_decoration = None
            box.update()
        lit_now.clear()
        box = glow() if callable(glow) else glow
        box = box if box is not None else content if isinstance(content, ft.Container) else None
        if on and box is not None:
            radius = box.border_radius if isinstance(box.border_radius, (int, float)) else 0
            box.foreground_decoration = outline(radius)
            box.update()
            lit_now.append(box)

    def dropped(e) -> None:
        lit(False)
        paths = [p for p in (e.data or []) if isinstance(p, str) and p]
        if paths:
            on_files(paths)

    return FileDrop(content=content, on_drop=dropped, on_enter=lambda e: lit(True),
                    on_leave=lambda e: lit(False), **kwargs)


def suffix(path: str) -> str:
    return Path(path).suffix.lower().lstrip(".")
