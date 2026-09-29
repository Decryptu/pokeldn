import flet as ft

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
    flat = ft.OutlineInputBorder(border_radius=8, side=ft.BorderSide(0, FIELD))
    return {ft.ControlState.FOCUSED: ft.OutlineInputBorder(border_radius=8, side=ft.BorderSide(1, BLUE)),
            ft.ControlState.DISABLED: flat, ft.ControlState.DEFAULT: flat}


def field(label: str = "", value: str = "", hint: str = "", mono: bool = False, **kwargs) -> ft.TextField:
    style = ft.TextStyle(size=13, color=TEXT, font_family=MONO if mono else None)
    return ft.TextField(value=value, label=label or None, hint_text=hint or None, text_style=style,
                        label_style=ft.TextStyle(size=12, color=MUTED), dense=True,
                        hint_style=ft.TextStyle(size=13, color=FAINT), bgcolor=FIELD, filled=True,
                        border=_border(), cursor_color=BLUE,
                        content_padding=ft.Padding(12, 10, 12, 10), **kwargs)


def dropdown(options: list[tuple[str, str]], value: str | None, on_select=None, **kwargs) -> ft.Dropdown:
    return ft.Dropdown(value=value, options=[ft.DropdownOption(key=k, text=t) for k, t in options],
                       on_select=on_select, dense=True, filled=True, bgcolor=FIELD, border=_border(),
                       text_size=13, expand=True, height=CONTROL_HEIGHT, content_padding=CONTROL_PADDING,
                       trailing_icon=pixel_icon("chevron-down", color=MUTED),
                       selected_trailing_icon=pixel_icon("chevron-up", color=BLUE),
                       menu_style=ft.MenuStyle(bgcolor=FIELD), **kwargs)


class _Button(ft.Button):
    def before_update(self):
        super().before_update()
        if isinstance(self.icon, ft.Image):
            colors = self.style.color
            self.icon.color = colors[ft.ControlState.DISABLED if self.disabled else ft.ControlState.DEFAULT]


def button(label: str, on_click=None, icon=None, color: str = BLUE, filled: bool = True,
           **kwargs) -> ft.Button:
    style = ft.ButtonStyle(
        bgcolor={ft.ControlState.DISABLED: FIELD, ft.ControlState.DEFAULT: color if filled else FIELD},
        color={ft.ControlState.DISABLED: FAINT, ft.ControlState.DEFAULT: "#FFFFFF" if filled else TEXT},
        shape=ft.RoundedRectangleBorder(radius=8), padding=CONTROL_PADDING,
        side=ft.BorderSide(1, EDGE) if not filled else ft.BorderSide(0, ft.Colors.TRANSPARENT),
        text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_600),
        overlay_color=ft.Colors.with_opacity(0.12, "#FFFFFF"),
        elevation={ft.ControlState.DISABLED: 0, ft.ControlState.DEFAULT: 6 if filled else 0},
        shadow_color=ft.Colors.with_opacity(0.6, color))
    icon_color = "#FFFFFF" if filled else TEXT
    kwargs.setdefault("height", CONTROL_HEIGHT)
    return _Button(label, icon=pixel_icon(icon, color=icon_color) if icon else None,
                     on_click=on_click, style=style, **kwargs)


def secondary_button(label: str, on_click=None, icon=None, **kwargs) -> ft.Button:
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
    return ft.Switch(value=value, active_color=BLUE, inactive_thumb_color=MUTED, inactive_track_color=HOVER,
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


def numbered(steps: list[str]) -> ft.Column:
    return ft.Column([
        ft.Row([
            ft.Container(text(str(i), 11, BLUE, weight=ft.FontWeight.W_700), width=22, height=22,
                         border_radius=11, alignment=ft.Alignment.CENTER,
                         bgcolor=ft.Colors.with_opacity(0.14, BLUE)),
            text(step, 13, expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        for i, step in enumerate(steps, 1)], spacing=10)
