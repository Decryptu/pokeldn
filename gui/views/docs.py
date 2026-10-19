import asyncio
import os
import re
from dataclasses import dataclass, field

import flet as ft

from gui import theme as t
from gui.views.widgets import MarkdownDocument, heading_sections
from pokeldn.app import i18n, preview
from pokeldn.app.paths import ROOT
from pokeldn.app.i18n import t as tr

DOCS = os.path.join(ROOT, "docs")
GUIDE = os.path.join(ROOT, "gui", "guide.md")
SITE = "https://decryptu.github.io/pokeldn/"


def _english(file: str) -> str:
    return GUIDE if file == "guide" else os.path.join(DOCS, file)


def _read(path) -> tuple[dict, str]:
    with open(path, encoding="utf-8") as source:
        return split_front_matter(source.read())


def document_path(file: str):
    """The language pack's copy of a page, else the English one (pokeldn.app.i18n.document)."""
    return i18n.document(file, _english(file))


def document_body(file: str) -> tuple[str, str | None]:
    """A page's Markdown, and for a pack's copy the English page whose anchors its headings keep."""
    path = document_path(file)
    if os.path.samefile(path, _english(file)):
        return _read(path)[1], None
    return _read(path)[1], _read(_english(file))[1]


def page_title(page: "Page") -> str:
    path = document_path(page.file)
    title = page.title if os.path.samefile(path, _english(page.file)) else _read(path)[0].get("title", page.title)
    return i18n.message(title)


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
    """The docs site's navigation: front matter titles, parents and nav_order. A page the site leaves
    out of its navigation (`nav_exclude`, an unreleased title) shows only while preview is enabled."""
    found, shown = [], preview.enabled()
    for name in sorted(os.listdir(DOCS)):
        if name.endswith(".md"):
            with open(os.path.join(DOCS, name), encoding="utf-8") as f:
                meta, _ = split_front_matter(f.read())
            if meta.get("title") and (shown or meta.get("nav_exclude") != "true"):
                found.append(Page(name, meta["title"], int(meta.get("nav_order", 99)), meta.get("parent", "")))
    by_title = {p.title: p for p in found}
    roots = []
    for p in sorted(found, key=lambda p: (p.order, p.title)):
        (by_title[p.parent].children if p.parent in by_title else roots).append(p)
    return roots


@dataclass
class Section:
    file: str
    page: str
    heading: str
    anchor: str
    text: str


def plain(markdown: str) -> str:
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", markdown)
    text = re.sub(r"(?m)^ {0,3}(#{1,6}|>|[-*+]|\d+\.)[ \t]+|^ {0,3}[-:| ]{3,}$|[`*|]|<[^>]+>", " ", text)
    return " ".join(text.split())


def index(tree: list[Page], guide_title: str) -> list[Section]:
    """Every page's sections, in navigation order, as plain text."""
    found = []

    def add(file, title):
        body, reference = document_body(file)
        for key, heading, source in heading_sections(body, reference=reference):
            text = plain(HEADING_LINE.sub("", source, count=1) if key else source)
            if text or heading:
                found.append(Section(file, title, plain(heading) or title, key, text))

    def walk(items):
        for p in items:
            add(p.file, page_title(p))
            walk(p.children)
    add("guide", guide_title)
    walk(tree)
    return found


HEADING_LINE = re.compile(r"^ {0,3}#{1,6}[^\n]*\n?")


def search(sections: list[Section], query: str, limit: int = 60) -> list[Section]:
    """Sections holding every word of the query; a word in a heading or a page title ranks first."""
    words = query.lower().split()
    scored = []
    for order, s in enumerate(sections):
        heading, page, text = s.heading.lower(), s.page.lower(), s.text.lower()
        if all(w in heading or w in page or w in text for w in words):
            score = sum(6 * (w in heading) + 3 * (w in page) + min(text.count(w), 5) for w in words)
            scored.append((-score, order, s))
    return [s for *_, s in sorted(scored)[:limit]]


def snippet(text: str, words: list[str], width: int = 150) -> list[tuple[str, bool]]:
    """A window of text around the first matched word, cut into (part, matched) runs."""
    lower = text.lower()
    hits = [lower.find(w) for w in words if w in lower]
    start = max(0, min(hits) - width // 3) if hits else 0
    window = text[start:start + width]
    if start:
        window = "..." + window.split(" ", 1)[-1]
    if start + width < len(text):
        window = window.rsplit(" ", 1)[0] + "..."
    pattern = re.compile("|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)), re.I)
    runs, cursor = [], 0
    for match in pattern.finditer(window) if words else ():
        runs += [(window[cursor:match.start()], False), (match[0], True)]
        cursor = match.end()
    return [r for r in runs + [(window[cursor:], False)] if r[0]]


class DocsView:
    def __init__(self, app):
        self.app = app
        self.tree = pages()
        self.file = "guide"
        self.open_parents: set[str] = set()
        self.query = ""
        self.sections: list[Section] | None = None
        self.search_field = t.field(hint=tr('docs.search_the_docs', 'Search the docs'),
                                    prefix_icon=ft.Container(t.pixel_icon("search", color=t.FAINT),
                                                             width=40, alignment=ft.Alignment.CENTER),
                                    on_change=self._search, on_submit=self._submit)
        self.nav = ft.ListView(spacing=1, padding=8, expand=True)
        self.markdown = MarkdownDocument(app, self._link)
        self.scroll = ft.ListView([ft.Container(self.markdown.control, width=860)], padding=ft.Padding(32, 24, 32, 32),
                                  expand=True)
        self.panes = t.Panes(
            (tr('docs.pane_pages', 'Pages'), "bulletlist", t.panel(ft.Column([
                t.panel_header(tr('docs.docs_7af023', 'Docs'), t.icon_button("external-link",
                                                     lambda e: self.app.page.run_task(self.app.open_url, SITE),
                                                     tr('docs.open_the_docs_website_a6f6df', 'Open the docs website'))),
                ft.Container(self.search_field, padding=ft.Padding(8, 0, 8, 4)),
                t.fade(self.nav),
            ], spacing=0, expand=True), width=t.SIDEBAR_WIDTH)),
            (tr('docs.pane_read', 'Read'), "book-open", t.surface(t.fade(self.scroll), radius=20, expand=True)))
        self.control = self.panes.control
        self.show("guide", update=False)

    def enter(self, doc: str = "", **_) -> None:
        if doc:
            self.show(doc, update=False)

    def show(self, file: str, update: bool = True) -> None:
        self.file = file
        body, reference = document_body(file)
        self.markdown.set_value(body, reference=reference)
        for root in self.tree:
            if file == root.file or any(file == c.file or any(file == g.file for g in c.children)
                                        for c in root.children):
                self.open_parents.add(root.file)
        self.render_nav()
        if update:
            self.control.update()

    def render_nav(self) -> None:
        if len(self.query.strip()) >= 2:
            self.nav.controls = self.result_rows()
            return
        rows = [self.row(tr('docs.start_here_2adc96', 'Start here'), "guide", 0)]
        rows.append(ft.Container(t.text(tr('docs.documentation_c20592', 'Documentation'), 11, t.FAINT, weight=ft.FontWeight.W_600),
                                 padding=ft.Padding(10, 14, 8, 4)))

        def walk(items, depth):
            for p in items:
                rows.append(self.row(page_title(p), p.file, depth, bool(p.children)))
                if p.children and p.file in self.open_parents:
                    walk(p.children, depth + 1)
        walk(self.tree, 0)
        self.nav.controls = rows

    def row(self, title: str, file: str, depth: int, folder: bool = False) -> ft.Control:
        active = file == self.file
        expanded = file in self.open_parents
        return ft.Container(ft.Row([
            t.text(title, 13, t.TEXT if active else (t.MUTED if depth else t.SOFT),
                   weight=ft.FontWeight.W_600 if depth == 0 else None, expand=True),
            t.pixel_icon("chevron-down" if expanded else "chevron-right",
                    color=t.FAINT) if folder else ft.Container(),
        ]), padding=ft.Padding(10 + depth * 14, 7, 8, 7), border_radius=12,
            bgcolor=t.SELECTED if active else None, on_click=lambda e: self._pick(file, folder))

    def results(self) -> list[Section]:
        if self.sections is None:   # built on the first search: every page is read once
            self.sections = index(self.tree, tr('docs.start_here_2adc96', 'Start here'))
        return search(self.sections, self.query)

    def result_rows(self) -> list[ft.Control]:
        found, words = self.results(), self.query.lower().split()
        if not found:
            return [ft.Container(t.text(tr('docs.no_page_matches', 'No page matches.'), 13, t.MUTED),
                                 padding=ft.Padding(10, 12, 8, 8))]
        return [ft.Container(ft.Column([
            t.text(s.heading, 13, t.TEXT, weight=ft.FontWeight.W_600, max_lines=2),
            t.text(s.page, 11, t.FAINT),
            ft.Text(spans=[ft.TextSpan(part, ft.TextStyle(color=t.BLUE if hit else t.MUTED,
                                                          weight=ft.FontWeight.W_600 if hit else None))
                           for part, hit in snippet(s.text, words)], size=12, max_lines=3) if s.text else ft.Container(),
        ], spacing=2, tight=True), padding=ft.Padding(10, 8, 8, 8), border_radius=12,
            bgcolor=t.SELECTED if s.file == self.file else None, on_click=lambda e, s=s: self._open(s.file, s.anchor))
            for s in found]

    def _search(self, e) -> None:
        self.query = e.control.value or ""
        self.render_nav()
        self.nav.update()

    def _submit(self, e) -> None:
        found = self.results() if len(self.query.strip()) >= 2 else []
        if found:
            self._open(found[0].file, found[0].anchor)

    def _open(self, file: str, anchor: str = "") -> None:
        self.panes.show(1, update=False)
        self.show(file)
        self.app.page.run_task(self._scroll, anchor)

    async def _scroll(self, anchor: str) -> None:
        if not anchor:
            await self.scroll.scroll_to(offset=0)
            return
        # A key resolves only once the client has laid the new page out; the first scroll can stop
        # short while the blocks below are still measured, so a second one settles it.
        for wait in (0.15, 0.5):
            await asyncio.sleep(wait)
            await self.scroll.scroll_to(scroll_key=anchor, duration=200)

    def _pick(self, file: str, folder: bool) -> None:
        if folder and file in self.open_parents and file == self.file:
            self.open_parents.discard(file)
            self.render_nav()
            self.nav.update()
            return
        if not folder:   # a phone brings the page forward; a folder's row only unfolds it
            self.panes.show(1, update=False)
        self.show(file)

    async def _link(self, e) -> None:
        url = str(e.data)
        if url.startswith(("http://", "https://")):
            await self.app.open_url(url)
            return
        target, _, fragment = url.partition("#")
        name = os.path.basename(target)
        if not target and fragment:
            await self._scroll(fragment)
        elif name.endswith(".md") and os.path.exists(os.path.join(DOCS, name)):
            self._open(name, fragment)
        elif target:
            await self.app.open_url(f"https://github.com/Decryptu/pokeldn/blob/main/{target.lstrip('./')}")
