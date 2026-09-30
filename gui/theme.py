import flet as ft
import flet.canvas as cv

from gui.icons import icon as pixel_icon

BG = "#08090B"
PANEL = "#111215"
CARD = "#17181C"
FIELD = "#202126"
HOVER = "#292A30"
BORDER = "#24262B"
EDGE = "#2E3036"
TEXT = "#ECEDEF"
MUTED = "#8D9099"
FAINT = "#5D6068"
BLUE = "#47AEFA"
BLUE_DEEP = "#3979EE"
RED = "#FD474D"
RED_DEEP = "#D93B56"
GREEN = "#3DD68C"
MONO = "monospace"
CONTROL_HEIGHT = 36
CONTROL_PADDING = ft.Padding(12, 8, 12, 8)
CONTROL_RADIUS = 8
BUTTON_DEPTH = 3
FLOAT = [ft.BoxShadow(blur_radius=30, offset=ft.Offset(0, 12), color=ft.Colors.with_opacity(0.55, "#000000"))]


def app_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=BLUE,
        color_scheme=ft.ColorScheme(primary=BLUE, secondary=RED, surface=PANEL, on_surface=TEXT,
                                    error=RED, outline=BORDER, surface_container_highest=FIELD),
        divider_color=BORDER,
        scrollbar_theme=ft.ScrollbarTheme(thickness=6, radius=3, thumb_color=HOVER),
        tooltip_theme=ft.TooltipTheme(decoration=ft.BoxDecoration(bgcolor=FIELD, border_radius=6),
                                     text_style=ft.TextStyle(color=TEXT, size=12)),
    )


def text(value: str, size: float = 13, color: str = TEXT, weight=None, **kwargs) -> ft.Text:
    return ft.Text(value, size=size, color=color, weight=weight, **kwargs)


def backdrop(content: ft.Control) -> ft.Container:
    """The window behind the panels: a dim checkerboard."""
    return ft.Container(content, expand=True, bgcolor=BG, padding=14,
                        image=ft.DecorationImage(src="grid.png", repeat=ft.ImageRepeat.REPEAT, scale=2,
                                                 alignment=ft.Alignment.TOP_LEFT))


def panel(content: ft.Control, width: float | None = None, expand=None, padding=0) -> ft.Container:
    return ft.Container(content, width=width, expand=expand, bgcolor=PANEL, padding=padding,
                        border_radius=16, border=ft.Border.all(1, BORDER), shadow=FLOAT)


def notch(*controls: ft.Control) -> ft.Row:
    """A small floating toolbar centred over the canvas; its groups are split by hairlines."""
    items: list[ft.Control] = []
    for control in controls:
        if items:
            items.append(ft.Container(width=1, height=20, bgcolor=EDGE))
        items.append(control)
    return ft.Row([ft.Container(ft.Row(items, spacing=10, tight=True), bgcolor=PANEL, border_radius=14,
                                padding=ft.Padding(12, 6, 8, 6), border=ft.Border.all(1, EDGE), shadow=FLOAT)],
                  alignment=ft.MainAxisAlignment.CENTER)


def panel_header(title: str, *actions: ft.Control) -> ft.Container:
    return ft.Container(
        ft.Row([text(title, 15, weight=ft.FontWeight.W_600), ft.Row(list(actions), spacing=4)],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        padding=ft.Padding(16, 14, 12, 14), border=ft.Border(bottom=ft.BorderSide(1, BORDER)))


def card(title: str, body: ft.Control | None = None, description: str = "",
         trailing: ft.Control | None = None, tip: str = "") -> ft.Container:
    head = [text(title, 13, weight=ft.FontWeight.W_600, expand=True)]
    if tip:
        head.append(pixel_icon("circle-info", color=FAINT, tooltip=tip))
    if trailing:
        head.append(trailing)
    rows: list[ft.Control] = [ft.Row(head, spacing=8)]
    if description:
        rows.append(text(description, 12, MUTED))
    if body:
        rows.append(body)
    return ft.Container(ft.Column(rows, spacing=10, tight=True), bgcolor=CARD, border_radius=14,
                        padding=14, border=ft.Border.all(1, BORDER), shadow=FLOAT)


def _border() -> dict:
    flat = ft.OutlineInputBorder(border_radius=CONTROL_RADIUS, side=ft.BorderSide(0, FIELD))
    return {ft.ControlState.FOCUSED: ft.OutlineInputBorder(border_radius=CONTROL_RADIUS, side=ft.BorderSide(1, BLUE)),
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
    control = _Field if uniform else ft.TextField
    return control(value=value, label=label or None, hint_text=hint or None, text_style=style,
                   label_style=ft.TextStyle(size=12, color=MUTED), dense=True,
                   hint_style=ft.TextStyle(size=13, color=FAINT), bgcolor=FIELD, filled=True,
                   border=_border(), cursor_color=BLUE,
                   content_padding=CONTROL_PADDING, text_vertical_align=ft.VerticalAlignment.CENTER, **kwargs)


def dropdown(options: list[tuple[str, str]], value: str | None, on_select=None, **kwargs) -> ft.Dropdown:
    return ft.Dropdown(value=value, options=[ft.DropdownOption(key=k, text=t) for k, t in options],
                       on_select=on_select, dense=True, filled=True, bgcolor=FIELD, border=_border(),
                       text_size=13, expand=True, height=CONTROL_HEIGHT, content_padding=CONTROL_PADDING,
                       trailing_icon=pixel_icon("chevron-down", color=MUTED),
                       selected_trailing_icon=pixel_icon("chevron-up", color=BLUE),
                       menu_style=ft.MenuStyle(bgcolor=FIELD), **kwargs)


def labeled_control(label: str, control: ft.Control, **kwargs) -> ft.Column:
    return ft.Column([ft.Container(text(label, 11, MUTED), height=16,
                                  alignment=ft.Alignment.CENTER_LEFT), control],
                     spacing=4, tight=True, **kwargs)


class _Button(ft.Container):
    def before_update(self):
        super().before_update()
        self.content.disabled = self.disabled
        if isinstance(self.content.icon, ft.Image):
            colors = self.content.style.color
            self.content.icon.color = colors[ft.ControlState.DISABLED if self.disabled else ft.ControlState.DEFAULT]
        self.shadow = [] if self.disabled or self.data is None else [ft.BoxShadow(
            blur_radius=0, spread_radius=0, offset=ft.Offset(0, BUTTON_DEPTH), color=self.data)]


def button(label: str, on_click=None, icon=None, color: str = BLUE, filled: bool = True,
           **kwargs) -> ft.Container:
    stroke = color if filled else EDGE
    style = ft.ButtonStyle(
        bgcolor={ft.ControlState.DISABLED: FIELD, ft.ControlState.DEFAULT: color if filled else FIELD},
        color={ft.ControlState.DISABLED: FAINT, ft.ControlState.DEFAULT: "#FFFFFF" if filled else TEXT},
        shape=ft.RoundedRectangleBorder(radius=CONTROL_RADIUS), padding=CONTROL_PADDING,
        side=ft.BorderSide(1, stroke),
        text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_600),
        overlay_color=ft.Colors.with_opacity(0.12, "#FFFFFF"),
        elevation=0, shadow_color=ft.Colors.TRANSPARENT)
    icon_color = "#FFFFFF" if filled else TEXT
    kwargs.setdefault("height", CONTROL_HEIGHT)
    return _Button(ft.Button(label, icon=pixel_icon(icon, color=icon_color) if icon else None,
                             on_click=on_click, style=style, elevation=0, height=kwargs["height"]),
                   bgcolor=color if filled else FIELD, border_radius=CONTROL_RADIUS,
                   shadow=[] if filled else [ft.BoxShadow(blur_radius=0, spread_radius=0,
                                                        offset=ft.Offset(0, BUTTON_DEPTH), color=stroke)],
                   data=None if filled else stroke, **kwargs)


def secondary_button(label: str, on_click=None, icon=None, **kwargs) -> ft.Container:
    return button(label, on_click, icon, filled=False, **kwargs)


def link_button(label: str, on_click=None) -> ft.TextButton:
    return ft.TextButton(label, on_click=on_click, height=CONTROL_HEIGHT,
                         style=ft.ButtonStyle(color=BLUE, padding=CONTROL_PADDING))


def icon_button(icon, on_click=None, tooltip: str = "", color: str = MUTED, **kwargs) -> ft.IconButton:
    return ft.IconButton(pixel_icon(icon, color=color), tooltip=tooltip or None,
                         on_click=on_click, width=32, height=32,
                         style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                         **kwargs)


def switch(value: bool, on_change) -> ft.Switch:
    return ft.Switch(value=value, height=CONTROL_HEIGHT, padding=0,
                     active_color=BLUE, inactive_thumb_color=MUTED, inactive_track_color=HOVER,
                     track_outline_color={ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT},
                     overlay_color={ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
                                    ft.ControlState.HOVERED: ft.Colors.TRANSPARENT,
                                    ft.ControlState.PRESSED: ft.Colors.TRANSPARENT,
                                    ft.ControlState.FOCUSED: ft.Colors.with_opacity(0.18, BLUE)},
                     splash_radius=16,
                     on_change=on_change)


def pill(label: str, color: str = MUTED) -> ft.Container:
    return ft.Container(text(label, 11, color, weight=ft.FontWeight.W_600),
                        padding=ft.Padding(8, 3, 8, 3), border_radius=20,
                        bgcolor=ft.Colors.with_opacity(0.14, color))


def segmented(options: list[tuple[str, str, str]], value: str, on_change) -> ft.Container:
    """The small pill switcher (Basic / All options)."""
    row = ft.Row(spacing=2, tight=True)

    def render(selected):
        row.controls = [
            ft.Container(ft.Row([
                pixel_icon(icon, color=BLUE if key == selected else FAINT),
                text(label, 12, TEXT if key == selected else MUTED, weight=ft.FontWeight.W_600),
            ], spacing=6, tight=True),
                padding=ft.Padding(12, 6, 14, 6), border_radius=8,
                bgcolor=HOVER if key == selected else None,
                border=ft.Border.all(1, EDGE if key == selected else ft.Colors.TRANSPARENT),
                on_click=lambda e, k=key: pick(k))
            for key, label, icon in options]

    def pick(key):
        render(key)
        row.update()
        on_change(key)

    render(value)
    return ft.Container(row, bgcolor=BG, border_radius=10, padding=3)


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
