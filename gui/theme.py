from dataclasses import fields
import base64
import os

import flet as ft
import flet.canvas as cv

from gui.icons import icon as pixel_icon

BG = "#0B0B0D"
PANEL = "#1C1C1F"
CARD = "#161618"
FIELD = "#232326"
HOVER = "#2C2C30"
OUTLINE = "#262629"
BORDER = "#2E2E32"
EDGE = "#3A3A3F"
DIVIDER = "#252528"
TEXT = "#F5F5F7"
SOFT = "#D1D1D6"
MUTED = "#A1A1A6"
FAINT = "#98989D"   # 4.8:1 on HOVER, the lightest surface it sits on (WCAG AA for small text)
BLUE = "#47AEFA"
RED = "#FD474D"
GREEN = "#3DD68C"
AMBER = "#FF9F0A"
SILVER = "#BCC3CE"
SELECTED = ft.Colors.with_opacity(0.14, BLUE)
MONO = "monospace"
CJK_FONT = "Noto Sans CJK SC"
# The CJK font draws ‘ ’ “ ” · … full-width; this one holds its Latin-width forms (scripts/gen_punctuation_font.py).
PUNCTUATION_FONT = "Noto Sans Punctuation"
FALLBACK_FONTS = [PUNCTUATION_FONT, CJK_FONT]
FONT_ASSETS = {PUNCTUATION_FONT: "fonts/NotoSansPunctuation.otf", CJK_FONT: "fonts/NotoSansCJKsc-Regular.otf"}
CONTROL_HEIGHT = 34
CONTROL_PADDING = ft.Padding(12, 8, 12, 8)
CONTROL_RADIUS = 8
CARD_PADDING = 18
CARD_RADIUS = 18
GAP = 12
SIDEBAR_WIDTH = 254
SESSION_WIDTH = 360
# A window narrower than this (a phone) shows one panel at a time and a bottom tab bar (docs/gui.md, Phones).
COMPACT_WIDTH = 760
READABLE_WIDTH = 720   # the options column's widest: a wider form spreads a field's label far from its value
compact = False
window_width = 0.0   # the page's width, kept by gui/main.py: a pane built later starts in the right layout
text_scale = 1.0     # Settings, Larger text: read once at launch by gui/main.py
# Flutter's default density on a desktop is compact, which takes 8 px off a text field (VisualDensity
# .defaultDensityForPlatform); gui/main.py sets it from the page's platform.
field_density = 8.0


def scaled(value: float) -> float:
    """A text size in points, scaled by the player's Larger text setting."""
    return round(value * text_scale, 1)


def app_theme() -> ft.Theme:
    from pokeldn.app.i18n import font_family
    return ft.Theme(
        font_family=font_family(),
        text_theme=ft.TextTheme(**{f.name: ft.TextStyle(font_family_fallback=FALLBACK_FONTS)
                                   for f in fields(ft.TextTheme)}),
        color_scheme_seed=BLUE,
        color_scheme=ft.ColorScheme(primary=BLUE, secondary=BLUE, surface=PANEL, on_surface=TEXT,
                                    error=RED, outline=BORDER, surface_container_highest=FIELD),
        divider_color=DIVIDER,
        card_theme=ft.CardTheme(margin=0),
        scrollbar_theme=ft.ScrollbarTheme(thickness=6, radius=3,
                                          thumb_color=ft.Colors.with_opacity(0.2, "#FFFFFF")),
        tooltip_theme=ft.TooltipTheme(decoration=ft.BoxDecoration(bgcolor=HOVER, border_radius=8),
                                      text_style=ft.TextStyle(color=TEXT, size=12, font_family=font_family(),
                                                              font_family_fallback=FALLBACK_FONTS)),
    )


def text(value: str, size: float = 13, color: str = TEXT, weight=None, **kwargs) -> ft.Text:
    kwargs.setdefault("style", ft.TextStyle(height=1.4, font_family_fallback=FALLBACK_FONTS))
    return ft.Text(value, size=scaled(size), color=color, weight=weight, **kwargs)


def backdrop(content: ft.Control) -> ft.Container:
    """The window behind the glass: a dim checkerboard."""
    return ft.Container(content, expand=True, bgcolor=BG, padding=GAP,
                        image=ft.DecorationImage(src="grid.png", repeat=ft.ImageRepeat.REPEAT, scale=2,
                                                 alignment=ft.Alignment.TOP_LEFT))


def glass(content: ft.Control, radius: float = 20, **kwargs) -> ft.Container:
    """Liquid Glass: the layer of navigation and controls that floats above the content, never the content itself."""
    # One colour on all four sides: Flutter leaves the corners of a mixed-colour border square.
    return ft.Container(
        content, blur=ft.Blur(30, 30), border_radius=radius, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        bgcolor=ft.Colors.with_opacity(0.68, "#1F1F22"),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.1, "#FFFFFF")),
        **kwargs)


def surface(content: ft.Control, *, bgcolor: str = CARD, radius: float = 14, **kwargs) -> ft.Container:
    """A solid surface in the content layer."""
    return ft.Container(content, bgcolor=bgcolor, border_radius=radius, **kwargs)


def panel(content: ft.Control, width: float | None = None, expand=None, padding=0) -> ft.Container:
    return glass(ft.Container(content, padding=padding), width=width, expand=expand)


TOOLBAR_ITEM = 32   # the icon buttons are this size
TOOLBAR_INSET = 4


CENTER_MIN = 440      # the flexible pane never gets narrower than this beside the others
NARROWED = 0.88       # a fixed pane's width when the window is a little short of room


class Panes:
    """A page's panels, laid out by the width they have (docs/gui.md, Window sizes): side by side;
    then the fixed panes narrowed; then, with three, the first two on one switcher beside the last;
    then one at a time on a switcher, as on a phone. `show` brings one forward, as choosing a tool
    brings its options."""

    def __init__(self, *panes: tuple[str, str, ft.Control]):
        self.panes = list(panes)
        self.widths = [pane.width for _, _, pane in panes]
        self.index = 0
        self.layout = ""
        self.switched: list[int] = []
        # Every pane stays on the page, hidden or not: a view updates its panes while another shows.
        self.holders = [ft.Container(expand=True) for _ in panes]
        self.switcher = ft.Container()
        self.control = ft.Container(expand=True, size_change_interval=50, on_size_change=self._resized)
        # A pane gets no size event when it first appears; the rail and the margins take 108 points.
        self._arrange(self._choose(window_width - 108) if window_width else "full")

    def _choose(self, width: float) -> str:
        fixed = [w for w in self.widths if w]
        gaps = GAP * (len(self.panes) - 1)
        if compact:
            return "single"
        if width >= sum(fixed) + CENTER_MIN + gaps:
            return "full"
        if width >= sum(fixed) * NARROWED + CENTER_MIN + gaps:
            return "narrow"
        if len(self.panes) == 3 and self.widths[2] and width >= self.widths[2] * NARROWED + CENTER_MIN + GAP:
            return "split"
        return "single"

    def _resized(self, e) -> None:
        layout = self._choose(e.width)
        if layout != self.layout:
            self._arrange(layout)
            self.control.update()

    def _arrange(self, layout: str) -> None:
        side_by_side = self.layout in ("full", "narrow")
        self.layout = layout
        for holder in self.holders:
            holder.content = None
        if layout in ("full", "narrow"):
            self.switched = []
            for (_, _, pane), width in zip(self.panes, self.widths):
                pane.width = (width if layout == "full" else round(width * NARROWED)) if width else None
                pane.expand = None if width else True
            self.control.content = ft.Row([p[2] for p in self.panes], spacing=GAP, expand=True,
                                          vertical_alignment=ft.CrossAxisAlignment.STRETCH)
            return
        self.switched = [0, 1] if layout == "split" else list(range(len(self.panes)))
        if side_by_side and None in self.widths:    # a window narrowed keeps the content in front
            self.index = self.widths.index(None)
        if self.index not in self.switched:
            self.index = self.switched[-1]
        for i in self.switched:
            pane = self.panes[i][2]
            pane.width, pane.expand = None, True
            self.holders[i].content = pane
            self.holders[i].visible = i == self.index
        self._render()
        column = ft.Column([self.switcher, *(self.holders[i] for i in self.switched)], spacing=8, expand=True)
        if layout == "single":
            self.control.content = column
            return
        last = self.panes[2][2]
        last.width, last.expand = round(self.widths[2] * NARROWED), None
        self.control.content = ft.Row([column, last], spacing=GAP, expand=True,
                                      vertical_alignment=ft.CrossAxisAlignment.STRETCH)

    def _render(self) -> None:
        self.switcher.content = notch(segmented([(str(i), self.panes[i][0], self.panes[i][1]) for i in self.switched],
                                                str(self.index), lambda value: self.show(int(value))))

    def show(self, index: int, update: bool = True) -> None:
        if index not in self.switched or index == self.index:
            return
        self.index = index
        for i in self.switched:
            self.holders[i].visible = i == index
        self._render()
        if update and self.control.page:
            self.control.update()


def readable(column: ft.Control, widest: float) -> ft.ShaderMask:
    """A faded, scrolled column as wide as the window allows, up to `widest`, centred."""
    view = ft.ListView([column], padding=ft.Padding(4, 8, 4, 24), expand=True)
    mask = fade(view)
    faded = mask.on_size_change

    def fit(e) -> None:
        faded(e)
        side = max(4, (e.width - widest) // 2)
        if view.padding.left != side:
            view.padding = ft.Padding(side, 8, side, 24)
            view.update()
    mask.on_size_change = fit
    return mask


def notch(*controls: ft.Control) -> ft.Row:
    """A small glass toolbar centred over the content; its groups are split by hairlines.
    Its corners are concentric with its items': outer radius = item radius + the even inset."""
    items: list[ft.Control] = []
    for control in controls:
        if items:
            items.append(ft.Container(width=1, height=18, bgcolor=ft.Colors.with_opacity(0.12, "#FFFFFF")))
        items.append(control)
    row = ft.Row(items, spacing=8, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return ft.Row([glass(ft.Container(row, padding=TOOLBAR_INSET), radius=TOOLBAR_ITEM / 2 + TOOLBAR_INSET)],
                  alignment=ft.MainAxisAlignment.CENTER)


def panel_header(title: str, *actions: ft.Control) -> ft.Container:
    return ft.Container(
        ft.Row([text(title, 15, weight=ft.FontWeight.W_600, expand=True), ft.Row(list(actions), spacing=2)],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding(18, 14, 12, 6))


def section(title: str, body: ft.Control | None = None, trailing: ft.Control | None = None) -> ft.Column:
    """A titled group inside a glass panel: the spacing separates it, no box."""
    head: list[ft.Control] = [text(title, 12, MUTED, weight=ft.FontWeight.W_600, expand=True)]
    if trailing:
        head.append(trailing)
    return ft.Column([ft.Row(head, spacing=8), *([body] if body else [])], spacing=8, tight=True)


def grid_rows(tiles: list[ft.Control], columns: int = 2, spacing: float = 6,
              stretch_last: bool = False) -> list[ft.Control]:
    """Tiles in rows of `columns`; the tiles of a row share its tallest tile's height. `stretch_last`
    lets a short last row's tiles share its width, as a lone raid seed does."""
    rows = []
    for i in range(0, len(tiles), columns):
        cells = tiles[i:i + columns]
        for cell in cells:
            cell.expand = 1
        if not stretch_last:
            cells += [ft.Container(expand=1) for _ in range(columns - len(cells))]
        rows.append(ft.Row(cells, spacing=spacing, intrinsic_height=True,
                           vertical_alignment=ft.CrossAxisAlignment.STRETCH))
    return rows


def grid(tiles: list[ft.Control], columns: int = 2, spacing: float = 6) -> ft.Column:
    return ft.Column(grid_rows(tiles, columns, spacing), spacing=spacing, tight=True)


class Flow:
    """Tiles or fields in rows of as many as the measured width gives each `min_width`; a fixed count
    per row squeezes a dropdown's text or a tile's summary out of a narrow column."""

    def __init__(self, controls: list[ft.Control], min_width: float = 160, spacing: float = 10,
                 stretch_last: bool = False):
        self.min_width, self.spacing, self.width, self.stretch_last = min_width, spacing, 0.0, stretch_last
        self.box = ft.Column(spacing=spacing, tight=True)
        self.control = ft.Container(self.box, size_change_interval=50, on_size_change=self._resized)
        self.columns = 0
        self.set(controls)

    def _fit(self) -> int:
        if not self.width:
            return max(1, len(self.items))
        return max(1, min(len(self.items), int((self.width + self.spacing) // (self.min_width + self.spacing))))

    def set(self, controls: list[ft.Control], single: bool = False) -> None:
        """New tiles; `single` lays them one to a row, as a message in place of tiles."""
        self.items, self.single = list(controls), single
        self._lay()

    def _lay(self) -> None:
        self.columns = 1 if self.single else self._fit()
        self.box.controls = (list(self.items) if self.single else
                             grid_rows(list(self.items), self.columns, self.spacing, self.stretch_last))

    def _resized(self, e) -> None:
        self.width = e.width
        if not self.single and self._fit() != self.columns:
            self._lay()
            self.control.update()


def field_grid(controls: list[ft.Control], min_width: float = 160) -> ft.Container:
    """Labelled fields in a Flow; a short last row's fields share its width."""
    return Flow(controls, min_width, 10, stretch_last=True).control


def card(title: str, body: ft.Control | None = None, description: str = "",
         trailing: ft.Control | None = None, tip: str = "") -> ft.Container:
    head = [text(title, 14, weight=ft.FontWeight.W_600, expand=True)]
    if tip:
        head.append(pixel_icon("circle-info", color=FAINT, tooltip=tip))
    if trailing:
        head.append(trailing)
    rows: list[ft.Control] = [ft.Row(head, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if description:
        rows.append(text(description, 12, MUTED))
    if body:
        rows.append(body)
    return card_box(ft.Column(rows, spacing=12, tight=True))


def card_box(content: ft.Control) -> ft.Container:
    """The options column's card: every card there, built by `card` or by hand, has this padding and corner."""
    return surface(ft.Container(content, padding=CARD_PADDING), radius=CARD_RADIUS)


def dialog(**kwargs) -> ft.AlertDialog:
    content = kwargs.get("content")
    if compact and isinstance(content, ft.Container) and (content.width or 0) > 280:
        content.width = None     # a phone's dialog is as wide as the screen allows
    if compact:
        kwargs.setdefault("inset_padding", ft.Padding(14, 24, 14, 24))
        kwargs.setdefault("actions_overflow_button_spacing", 8)
    return ft.AlertDialog(bgcolor=PANEL, elevation=24,
                          shape=ft.RoundedRectangleBorder(
                              radius=20, side=ft.BorderSide(1, ft.Colors.with_opacity(0.08, "#FFFFFF"))),
                          barrier_color=ft.Colors.with_opacity(0.6, "#000000"), **kwargs)


def _border(color: str = "") -> dict:
    flat = ft.OutlineInputBorder(border_radius=CONTROL_RADIUS, side=ft.BorderSide(1, color or ft.Colors.TRANSPARENT))
    return {ft.ControlState.FOCUSED: ft.OutlineInputBorder(border_radius=CONTROL_RADIUS,
                                                           side=ft.BorderSide(1.5, color or BLUE)),
            ft.ControlState.DISABLED: flat, ft.ControlState.DEFAULT: flat}


def mark_invalid(control: ft.TextField, invalid: bool) -> None:
    """A red border with no message: an empty `error` keeps Flet's message line, which squeezes a fixed-height field."""
    control.border = _border(RED if invalid else "")


def field(label: str = "", value: str = "", hint: str = "", mono: bool = False, digits: bool = False,
          limit: int = 0, **kwargs) -> ft.TextField:
    """`digits` takes 0-9 only; `limit` caps the length. Both are one regex over the whole value:
    Flet's max_length squeezes a fixed-height field into wrapping, and its filter refuses a whole edit."""
    if digits or limit:
        count = f"{{0,{limit}}}" if limit else "*"
        kwargs.setdefault("input_filter", ft.InputFilter(f"^{'[0-9]' if digits else '.'}{count}$"))
    if digits:
        kwargs.setdefault("keyboard_type", ft.KeyboardType.NUMBER)
    style = ft.TextStyle(size=13, color=TEXT, font_family=MONO if mono else None,
                         font_family_fallback=FALLBACK_FONTS)
    kwargs.setdefault("size_constraints", ft.BoxConstraints(min_height=CONTROL_HEIGHT))
    kwargs.setdefault("content_padding", CONTROL_PADDING)
    if not kwargs.get("multiline") and not label and "height" not in kwargs:
        # A forced line height, never a height: Flet wraps a sized field in a SizedBox, and an error that
        # adds or drops it rebuilds the input, which then loses focus mid-word.
        line = CONTROL_HEIGHT - kwargs["content_padding"].top - kwargs["content_padding"].bottom + field_density
        kwargs.setdefault("strut_style", ft.StrutStyle(size=13, height=line / 13, force_strut_height=True))
    return ft.TextField(value=value, label=label or None, hint_text=hint or None, text_style=style,
                        label_style=ft.TextStyle(size=12, color=MUTED), dense=True,
                        hint_style=ft.TextStyle(size=13, color=FAINT), bgcolor=FIELD, filled=True,
                        border=_border(), cursor_color=BLUE,
                        text_vertical_align=ft.VerticalAlignment.CENTER, **kwargs)


def dropdown(options: list[tuple[str, str]], value: str | None, on_select=None, **kwargs) -> ft.Dropdown:
    if on_select and kwargs.get("editable"):
        chosen = on_select

        def on_select(e):
            # Enter on typed text selects nothing: value None. Take the option it names, or ignore it.
            if e.control.value is None:
                typed = (e.control.text or "").strip().casefold()
                e.control.value = next((o.key for o in e.control.options if typed and (o.text or "").casefold() == typed), None)
                if e.control.value is None:
                    return
                e.control.update()
            chosen(e)
    return ft.Dropdown(value=value, options=[ft.DropdownOption(key=k, text=t) for k, t in options],
                       on_select=on_select, dense=True, filled=True, bgcolor=FIELD, border=_border(),
                       text_size=13, text_style=ft.TextStyle(font_family_fallback=FALLBACK_FONTS),
                       expand=True, height=CONTROL_HEIGHT, content_padding=CONTROL_PADDING,
                       trailing_icon=pixel_icon("chevron-down", color=MUTED),
                       selected_trailing_icon=pixel_icon("chevron-up", color=BLUE),
                       menu_style=ft.MenuStyle(bgcolor=PANEL, shape=ft.RoundedRectangleBorder(radius=10)),
                       **kwargs)


def field_line(control: ft.Control, alignment: ft.Alignment = ft.Alignment.CENTER, **kwargs) -> ft.Container:
    """A bare control on a field's line: as tall as the field and centred on it. In a row aligned END beside
    labeled controls it sits level with their fields; a hard-coded height or margin drifts off it."""
    return ft.Container(control, height=CONTROL_HEIGHT, alignment=alignment, **kwargs)


def labeled_control(label: str, control: ft.Control, **kwargs) -> ft.Column:
    return ft.Column([ft.Container(text(label, 11, MUTED),
                                   alignment=ft.Alignment.CENTER_LEFT), control],
                     spacing=4, tight=True, **kwargs)


class _Button(ft.Button):
    def before_update(self):
        super().before_update()
        if isinstance(self.icon, ft.Image):   # a pixel icon is an image: it takes the label's colour by hand
            colors = self.style.color
            self.icon.color = colors[ft.ControlState.DISABLED if self.disabled else ft.ControlState.DEFAULT]


def button(label: str, on_click=None, icon=None, color: str = BLUE, filled: bool = True,
           **kwargs) -> ft.Button:
    """A capsule. Filled carries the colour and is the one likely action in a view; the rest are not filled."""
    ink = BG if filled else TEXT
    style = ft.ButtonStyle(
        bgcolor={ft.ControlState.DISABLED: ft.Colors.with_opacity(0.05, "#FFFFFF"),
                 ft.ControlState.DEFAULT: color if filled else ft.Colors.with_opacity(0.09, "#FFFFFF")},
        color={ft.ControlState.DISABLED: FAINT, ft.ControlState.DEFAULT: ink},
        shape=ft.StadiumBorder(), padding=ft.Padding(16, 8, 16, 8),
        side={ft.ControlState.FOCUSED: ft.BorderSide(2, ft.Colors.with_opacity(0.6, BLUE)),
              ft.ControlState.DEFAULT: ft.BorderSide(0, ft.Colors.TRANSPARENT)},
        text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_500, font_family_fallback=FALLBACK_FONTS),
        overlay_color={ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
                       ft.ControlState.HOVERED: ft.Colors.with_opacity(0.08, "#FFFFFF"),
                       ft.ControlState.PRESSED: ft.Colors.with_opacity(0.14, "#000000")},
        elevation=0, shadow_color=ft.Colors.TRANSPARENT)
    kwargs.setdefault("height", CONTROL_HEIGHT)
    return _Button(label, icon=pixel_icon(icon, color=ink) if icon else None, on_click=on_click,
                   style=style, elevation=0, **kwargs)


def secondary_button(label: str, on_click=None, icon=None, **kwargs) -> ft.Button:
    return button(label, on_click, icon, filled=False, **kwargs)


def link_button(label: str, on_click=None) -> ft.TextButton:
    return ft.TextButton(label, on_click=on_click, height=CONTROL_HEIGHT,
                         style=ft.ButtonStyle(color=BLUE, padding=ft.Padding(10, 6, 10, 6),
                                              shape=ft.StadiumBorder(),
                                              overlay_color=ft.Colors.with_opacity(0.08, BLUE)))


def icon_button(icon, on_click=None, tooltip: str = "", color: str = MUTED, **kwargs) -> ft.IconButton:
    return ft.IconButton(pixel_icon(icon, color=color), tooltip=tooltip or None,
                         on_click=on_click, width=32, height=32,
                         style=ft.ButtonStyle(shape=ft.CircleBorder(),
                                              overlay_color=ft.Colors.with_opacity(0.08, "#FFFFFF")),
                         **kwargs)


def switch(value: bool, on_change) -> ft.Switch:
    return ft.Switch(value=value, height=CONTROL_HEIGHT, padding=0,
                     active_color="#FFFFFF", active_track_color=BLUE,
                     inactive_thumb_color="#FFFFFF", inactive_track_color="#3A3A3C",
                     track_outline_color={ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT},
                     overlay_color={ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
                                    ft.ControlState.HOVERED: ft.Colors.TRANSPARENT,
                                    ft.ControlState.PRESSED: ft.Colors.TRANSPARENT,
                                    ft.ControlState.FOCUSED: ft.Colors.with_opacity(0.18, BLUE)},
                     splash_radius=16,
                     on_change=on_change)


def badge(label: str, color: str = MUTED, icon: str = "circle-info") -> ft.Row:
    return ft.Row([pixel_icon(icon, size=12, color=color), text(label, 12, SOFT)],
                  spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def chip(label: str, icon: str | None = None, color: str = MUTED) -> ft.Container:
    """A small capsule holding a fact: an icon in its colour and a label."""
    row = [pixel_icon(icon, size=12, color=color)] if icon else []
    row.append(text(label, 12, SOFT, weight=ft.FontWeight.W_500))
    return ft.Container(ft.Row(row, spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=ft.Padding(10, 3, 10, 3), border_radius=999,
                        bgcolor=ft.Colors.with_opacity(0.06, "#FFFFFF"))


def segmented(options: list[tuple[str, str, str]], value: str, on_change, wrap: bool = False) -> ft.Row:
    """The capsule switcher (Basic / Advanced); it sits on the glass toolbar. `wrap` lets a long one break
    onto a second line: each capsule is then sized by its padding, since a centred one fills the line."""
    row = ft.Row(spacing=0, tight=True, wrap=wrap, run_spacing=4)
    size = ({"padding": ft.Padding(12, 8, 14, 8)} if wrap else
            {"height": TOOLBAR_ITEM, "padding": ft.Padding(12, 0, 14, 0), "alignment": ft.Alignment.CENTER})

    def render(selected):
        row.controls = [
            ft.Container(ft.Row([
                pixel_icon(icon, color=BLUE if key == selected else FAINT),
                text(label, 12, TEXT if key == selected else MUTED, weight=ft.FontWeight.W_600),
            ], spacing=6, tight=True), border_radius=TOOLBAR_ITEM / 2, **size,
                bgcolor=ft.Colors.with_opacity(0.14, "#FFFFFF") if key == selected else None,
                on_click=lambda e, k=key: pick(k))
            for key, label, icon in options]

    def pick(key):
        render(key)
        row.update()
        on_change(key)

    render(value)
    return row


def choice_row(label: str, options: list[tuple[str, str, str]], value: str, on_change) -> ft.Column:
    """A labelled capsule switcher on a card: one of a few ways to run the same thing (Hosts / Joins)."""
    track = ft.Container(segmented(options, value, on_change, wrap=True), bgcolor=FIELD,
                         border_radius=TOOLBAR_ITEM / 2 + 3, padding=3)
    return labeled_control(label, ft.Row([track], wrap=True))


def fade(scrollable: ft.ScrollableControl, size: float = 24) -> ft.ShaderMask:
    """The scrollable, its top and bottom edges fading out over size px while content lies beyond them."""
    edges = {"height": 0.0, "top": False, "bottom": not getattr(scrollable, "auto_scroll", False)}
    mask = ft.ShaderMask(content=scrollable, blend_mode=ft.BlendMode.DST_IN, expand=scrollable.expand,
                         shader=ft.LinearGradient(colors=["#FFFFFFFF", "#FFFFFFFF"]))

    def paint() -> bool:
        stop = min(size / edges["height"], 0.5) if edges["height"] else 0.0
        clear, solid = "#00FFFFFF", "#FFFFFFFF"
        shader = ft.LinearGradient(begin=ft.Alignment.TOP_CENTER, end=ft.Alignment.BOTTOM_CENTER,
                                   colors=[clear if edges["top"] else solid, solid, solid,
                                           clear if edges["bottom"] else solid],
                                   stops=[0, stop, 1 - stop, 1])
        changed = shader != mask.shader
        mask.shader = shader
        return changed

    # A scroll or size event otherwise ends in Flet's automatic update of the whole page: on a phone,
    # where a run shares the interpreter, an auto-scrolling log cost 72 ms per line (examples/android).
    def resized(e) -> None:
        ft.context.disable_auto_update()
        edges["height"] = e.height
        if paint():
            mask.update()

    previous = scrollable.on_scroll

    def scrolled(e) -> None:
        ft.context.disable_auto_update()
        top, bottom = e.pixels > e.min_scroll_extent + 1, e.pixels < e.max_scroll_extent - 1
        if (top, bottom) != (edges["top"], edges["bottom"]):
            edges["top"], edges["bottom"] = top, bottom
            if paint():
                mask.update()
        if previous:
            previous(e)

    scrollable.on_scroll = scrolled
    mask.on_size_change = resized
    paint()
    return mask


def step_list(steps: list[str]) -> ft.Column:
    rows = []
    for index, step in enumerate(steps):
        first, last = index == 0, index == len(steps) - 1
        lead = 0
        gap = 0 if last else 14

        def resize(e, initial=first, final=last, top=lead, bottom=gap):
            center = top + (e.height - top - bottom) / 2
            stroke = ft.Paint(color=MUTED, stroke_width=1, style=ft.PaintingStyle.STROKE)
            shapes = [cv.Circle(9, center, 4,
                                paint=ft.Paint(color=MUTED, stroke_width=1.5, style=ft.PaintingStyle.STROKE))]
            ranges = ([] if initial else [(0, center - 7)])
            if not final:
                ranges.append((center + 7, e.height))
            for start, end in ranges:
                y = start
                while y < end:
                    shapes.append(cv.Line(9, y, 9, min(y + 3, end), paint=stroke))
                    y += 7
            e.control.shapes = shapes
            e.control.update()

        rows.append(ft.Row([
            cv.Canvas([], width=18, on_resize=resize),
            ft.Container(text(step, 13), expand=True, padding=ft.Padding(0, lead, 0, gap)),
        ], spacing=10, intrinsic_height=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH))
    return ft.Column(rows, spacing=0, tight=True)


def image_src(data: bytes) -> bytes | str:
    """An image's bytes as an ft.Image src. iOS's WKWebView draws nothing for a bytes src and draws a
    data URI (examples/ios/README.md); the decoder reads the format from the bytes, not the label."""
    if os.environ.get("POKELDN_PLATFORM") == "ios":
        return "data:image/png;base64," + base64.b64encode(data).decode()
    return data
