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
FAINT = "#86868B"
BLUE = "#47AEFA"
RED = "#FD474D"
GREEN = "#3DD68C"
AMBER = "#FF9F0A"
SELECTED = ft.Colors.with_opacity(0.14, BLUE)
MONO = "monospace"
CONTROL_HEIGHT = 34
CONTROL_PADDING = ft.Padding(12, 8, 12, 8)
CONTROL_RADIUS = 8
GAP = 12
SIDEBAR_WIDTH = 254
SESSION_WIDTH = 360


def app_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=BLUE,
        color_scheme=ft.ColorScheme(primary=BLUE, secondary=BLUE, surface=PANEL, on_surface=TEXT,
                                    error=RED, outline=BORDER, surface_container_highest=FIELD),
        divider_color=DIVIDER,
        card_theme=ft.CardTheme(margin=0),
        scrollbar_theme=ft.ScrollbarTheme(thickness=6, radius=3,
                                          thumb_color=ft.Colors.with_opacity(0.2, "#FFFFFF")),
        tooltip_theme=ft.TooltipTheme(decoration=ft.BoxDecoration(bgcolor=HOVER, border_radius=8),
                                      text_style=ft.TextStyle(color=TEXT, size=12)),
    )


def text(value: str, size: float = 13, color: str = TEXT, weight=None, **kwargs) -> ft.Text:
    kwargs.setdefault("style", ft.TextStyle(height=1.4))
    return ft.Text(value, size=size, color=color, weight=weight, **kwargs)


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
        gradient=ft.LinearGradient(begin=ft.Alignment.TOP_CENTER, end=ft.Alignment.BOTTOM_CENTER,
                                   colors=[ft.Colors.with_opacity(0.72, "#26262A"),
                                           ft.Colors.with_opacity(0.64, "#18181B")]),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.1, "#FFFFFF")),
        **kwargs)


def surface(content: ft.Control, *, bgcolor: str = CARD, radius: float = 14, **kwargs) -> ft.Container:
    """A solid surface in the content layer."""
    return ft.Container(content, bgcolor=bgcolor, border_radius=radius, **kwargs)


def panel(content: ft.Control, width: float | None = None, expand=None, padding=0) -> ft.Container:
    return glass(ft.Container(content, padding=padding), width=width, expand=expand)


TOOLBAR_ITEM = 32   # the icon buttons are this size
TOOLBAR_INSET = 4


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
        ft.Row([text(title, 15, weight=ft.FontWeight.W_600), ft.Row(list(actions), spacing=2)],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding(18, 14, 12, 6), height=52)


def section(title: str, body: ft.Control | None = None, trailing: ft.Control | None = None) -> ft.Column:
    """A titled group inside a glass panel: the spacing separates it, no box."""
    head: list[ft.Control] = [text(title, 12, MUTED, weight=ft.FontWeight.W_600, expand=True)]
    if trailing:
        head.append(trailing)
    return ft.Column([ft.Row(head, spacing=8), *([body] if body else [])], spacing=8, tight=True)


def card(title: str, body: ft.Control | None = None, description: str = "",
         trailing: ft.Control | None = None, tip: str = "") -> ft.Container:
    head = [text(title, 13, weight=ft.FontWeight.W_600, expand=True)]
    if tip:
        head.append(pixel_icon("circle-info", color=FAINT, tooltip=tip))
    if trailing:
        head.append(trailing)
    rows: list[ft.Control] = [ft.Row(head, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if description:
        rows.append(text(description, 12, MUTED))
    if body:
        rows.append(body)
    return surface(ft.Container(ft.Column(rows, spacing=10, tight=True), padding=16))


def dialog(**kwargs) -> ft.AlertDialog:
    return ft.AlertDialog(bgcolor=PANEL, elevation=24,
                          shape=ft.RoundedRectangleBorder(
                              radius=20, side=ft.BorderSide(1, ft.Colors.with_opacity(0.08, "#FFFFFF"))),
                          barrier_color=ft.Colors.with_opacity(0.6, "#000000"), **kwargs)


def _border() -> dict:
    flat = ft.OutlineInputBorder(border_radius=CONTROL_RADIUS, side=ft.BorderSide(1, ft.Colors.TRANSPARENT))
    return {ft.ControlState.FOCUSED: ft.OutlineInputBorder(border_radius=CONTROL_RADIUS,
                                                           side=ft.BorderSide(1.5, BLUE)),
            ft.ControlState.DISABLED: flat, ft.ControlState.DEFAULT: flat}


class _Field(ft.TextField):
    def before_update(self):
        super().before_update()
        details = self.error or self.helper or self.counter
        self.height = None if details else CONTROL_HEIGHT
        self.fit_parent_size = not bool(details)


def field(label: str = "", value: str = "", hint: str = "", mono: bool = False, **kwargs) -> ft.TextField:
    style = ft.TextStyle(size=13, color=TEXT, font_family=MONO if mono else None)
    uniform = not kwargs.get("multiline") and not label and "height" not in kwargs
    if uniform:
        kwargs.setdefault("height", CONTROL_HEIGHT)
        kwargs.setdefault("fit_parent_size", True)
    kwargs.setdefault("size_constraints", ft.BoxConstraints(min_height=CONTROL_HEIGHT))
    kwargs.setdefault("content_padding", CONTROL_PADDING)
    control = _Field if uniform else ft.TextField
    return control(value=value, label=label or None, hint_text=hint or None, text_style=style,
                   label_style=ft.TextStyle(size=12, color=MUTED), dense=True,
                   hint_style=ft.TextStyle(size=13, color=FAINT), bgcolor=FIELD, filled=True,
                   border=_border(), cursor_color=BLUE,
                   text_vertical_align=ft.VerticalAlignment.CENTER, **kwargs)


def dropdown(options: list[tuple[str, str]], value: str | None, on_select=None, **kwargs) -> ft.Dropdown:
    return ft.Dropdown(value=value, options=[ft.DropdownOption(key=k, text=t) for k, t in options],
                       on_select=on_select, dense=True, filled=True, bgcolor=FIELD, border=_border(),
                       text_size=13, expand=True, height=CONTROL_HEIGHT, content_padding=CONTROL_PADDING,
                       trailing_icon=pixel_icon("chevron-down", color=MUTED),
                       selected_trailing_icon=pixel_icon("chevron-up", color=BLUE),
                       menu_style=ft.MenuStyle(bgcolor=PANEL, shape=ft.RoundedRectangleBorder(radius=10)),
                       **kwargs)


def labeled_control(label: str, control: ft.Control, **kwargs) -> ft.Column:
    return ft.Column([ft.Container(text(label, 11, MUTED), height=16,
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
        text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_500),
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

    def resized(e) -> None:
        edges["height"] = e.height
        if paint():
            mask.update()

    previous = scrollable.on_scroll

    def scrolled(e) -> None:
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
        lead = 22 if first else 0
        gap = 0 if last else 14

        def resize(e, initial=first, final=last, top=lead, bottom=gap):
            center = top + (e.height - top - bottom) / 2
            stroke = ft.Paint(color=MUTED, stroke_width=1, style=ft.PaintingStyle.STROKE)
            shapes = [cv.Circle(9, center, 4,
                                paint=ft.Paint(color=MUTED, stroke_width=1.5, style=ft.PaintingStyle.STROKE))]
            if initial:
                end = center - 7
                shapes.append(cv.Line(9, 0, 9, end, paint=ft.Paint(
                    stroke_width=1, style=ft.PaintingStyle.STROKE,
                    gradient=ft.PaintLinearGradient(begin=ft.Offset(9, 0), end=ft.Offset(9, end),
                                                   colors=[ft.Colors.with_opacity(0, MUTED), MUTED]))))
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
