import os
import re
from dataclasses import dataclass, field

import flet as ft

from gui import theme as t
from gui.paths import ROOT

DOCS = os.path.join(ROOT, "docs")
GUIDE = os.path.join(ROOT, "gui", "guide.md")
SITE = "https://decryptu.github.io/pokeldn/"


@dataclass
class Page:
    file: str
    title: str
    order: int
    parent: str = ""
    children: list["Page"] = field(default_factory=list)


def split_front_matter(text: str) -> tuple[dict, str]:
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not match:
        return {}, text
    meta = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    return {k.strip(): v.strip() for k, v in meta.items()}, text[match.end():]


def pages() -> list[Page]:
    """The docs site's navigation: front matter titles, parents and nav_order."""
    found = []
    for name in sorted(os.listdir(DOCS)):
        if name.endswith(".md"):
            with open(os.path.join(DOCS, name), encoding="utf-8") as f:
                meta, _ = split_front_matter(f.read())
            if meta.get("title"):
                found.append(Page(name, meta["title"], int(meta.get("nav_order", 99)), meta.get("parent", "")))
    by_title = {p.title: p for p in found}
    roots = []
    for p in sorted(found, key=lambda p: (p.order, p.title)):
        (by_title[p.parent].children if p.parent in by_title else roots).append(p)
    return roots


class DocsView:
    def __init__(self, app):
        self.app = app
        self.tree = pages()
        self.file = "guide"
        self.open_parents: set[str] = set()
        self.nav = ft.ListView(spacing=1, padding=8, expand=True)
        self.markdown = ft.Markdown(
            "", selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, on_tap_link=self._link,
            md_style_sheet=ft.MarkdownStyleSheet(
                p_text_style=ft.TextStyle(size=14, color="#D4D6DB", height=1.55),
                h1_text_style=ft.TextStyle(size=26, weight=ft.FontWeight.W_700, color=t.TEXT),
                h2_text_style=ft.TextStyle(size=19, weight=ft.FontWeight.W_600, color=t.TEXT),
                h3_text_style=ft.TextStyle(size=16, weight=ft.FontWeight.W_600, color=t.TEXT),
                a_text_style=ft.TextStyle(color=t.BLUE),
                code_text_style=ft.TextStyle(font_family=t.MONO, size=12.5, color="#E6C07B",
                                             bgcolor=t.FIELD),
                codeblock_decoration=ft.BoxDecoration(bgcolor=t.BG, border_radius=8),
                codeblock_padding=12,
                table_head_text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_600, color=t.TEXT),
                table_body_text_style=ft.TextStyle(size=13, color="#D4D6DB"),
                table_cells_padding=ft.Padding(8, 6, 8, 6),
                block_spacing=14,
            ))
        self.scroll = ft.ListView([ft.Container(self.markdown, width=860)], padding=ft.Padding(32, 24, 32, 32),
                                  expand=True)
        self.control = ft.Row([
            t.panel(ft.Column([
                t.panel_header("Docs", t.icon_button(ft.Icons.OPEN_IN_NEW_ROUNDED,
                                                     lambda e: self.app.page.run_task(self.app.open_url, SITE),
                                                     "Open the docs website")),
                self.nav,
            ], spacing=0, expand=True), width=270),
            t.panel(self.scroll, expand=True),
        ], spacing=12, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self.show("guide", update=False)

    def enter(self, doc: str = "", **_) -> None:
        if doc:
            self.show(doc, update=False)

    def show(self, file: str, update: bool = True) -> None:
        self.file = file
        path = GUIDE if file == "guide" else os.path.join(DOCS, file)
        with open(path, encoding="utf-8") as f:
            _, body = split_front_matter(f.read())
        self.markdown.value = body
        for root in self.tree:
            if file == root.file or any(file == c.file or any(file == g.file for g in c.children)
                                        for c in root.children):
                self.open_parents.add(root.file)
        self.render_nav()
        if update:
            self.control.update()

    def render_nav(self) -> None:
        rows = [self.row("Start here", "guide", 0)]
        rows.append(ft.Container(t.text("DOCUMENTATION", 10, t.FAINT, weight=ft.FontWeight.W_700),
                                 padding=ft.Padding(10, 14, 8, 4)))

        def walk(items, depth):
            for p in items:
                rows.append(self.row(p.title, p.file, depth, bool(p.children)))
                if p.children and p.file in self.open_parents:
                    walk(p.children, depth + 1)
        walk(self.tree, 0)
        self.nav.controls = rows

    def row(self, title: str, file: str, depth: int, folder: bool = False) -> ft.Control:
        active = file == self.file
        expanded = file in self.open_parents
        return ft.Container(ft.Row([
            t.text(title, 13 if depth == 0 else 12.5, t.TEXT if active else (t.MUTED if depth else "#C5C7CD"),
                   weight=ft.FontWeight.W_600 if depth == 0 else None, expand=True),
            ft.Icon(ft.Icons.EXPAND_MORE_ROUNDED if expanded else ft.Icons.CHEVRON_RIGHT_ROUNDED, size=16,
                    color=t.FAINT) if folder else ft.Container(),
        ]), padding=ft.Padding(10 + depth * 14, 7, 8, 7), border_radius=8,
            bgcolor=t.HOVER if active else None, on_click=lambda e: self._pick(file, folder))

    def _pick(self, file: str, folder: bool) -> None:
        if folder and file in self.open_parents and file == self.file:
            self.open_parents.discard(file)
            self.render_nav()
            self.nav.update()
            return
        self.show(file)

    async def _link(self, e) -> None:
        url = str(e.data)
        if url.startswith(("http://", "https://")):
            await self.app.open_url(url)
            return
        target = url.split("#")[0]
        name = os.path.basename(target)
        if name.endswith(".md") and os.path.exists(os.path.join(DOCS, name)):
            self.show(name)
        elif target:
            await self.app.open_url(f"https://github.com/Decryptu/pokeldn/blob/main/{target.lstrip('./')}")
