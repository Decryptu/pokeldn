import flet as ft

BG = "#0A0B0D"
PANEL = "#131417"
CARD = "#1A1B1F"
FIELD = "#222328"
HOVER = "#2A2B31"
BORDER = "#25272C"
TEXT = "#ECEDEF"
MUTED = "#8D9099"
FAINT = "#5D6068"
BLUE = "#47AEFA"
BLUE_DEEP = "#3979EE"
RED = "#FD474D"
RED_DEEP = "#D93B56"
GREEN = "#3DD68C"
AMBER = "#F5B544"
MONO = "monospace"


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


def panel(content: ft.Control, width: float | None = None, expand=None, padding=0) -> ft.Container:
    return ft.Container(content, width=width, expand=expand, bgcolor=PANEL, padding=padding,
                        border_radius=14, border=ft.Border.all(1, BORDER))


def panel_header(title: str, *actions: ft.Control) -> ft.Container:
    return ft.Container(
        ft.Row([text(title, 15, weight=ft.FontWeight.W_600), ft.Row(list(actions), spacing=4)],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        padding=ft.Padding(16, 14, 12, 14), border=ft.Border(bottom=ft.BorderSide(1, BORDER)))


def card(title: str, body: ft.Control | None = None, description: str = "",
         trailing: ft.Control | None = None, tip: str = "") -> ft.Container:
    head = [text(title, 13, weight=ft.FontWeight.W_600, expand=True)]
    if tip:
        head.append(ft.Icon(ft.Icons.INFO_OUTLINE, size=15, color=FAINT, tooltip=tip))
    if trailing:
        head.append(trailing)
    rows: list[ft.Control] = [ft.Row(head, spacing=8)]
    if description:
        rows.append(text(description, 12, MUTED))
    if body:
        rows.append(body)
    return ft.Container(ft.Column(rows, spacing=10, tight=True), bgcolor=CARD, border_radius=12,
                        padding=14, border=ft.Border.all(1, BORDER))


def _border() -> dict:
    return {ft.ControlState.DEFAULT: ft.OutlineInputBorder(border_radius=8, side=ft.BorderSide(0, FIELD)),
            ft.ControlState.FOCUSED: ft.OutlineInputBorder(border_radius=8, side=ft.BorderSide(1, BLUE))}


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
                       text_size=13, expand=True,
                       menu_style=ft.MenuStyle(bgcolor=FIELD), **kwargs)


def button(label: str, on_click=None, icon=None, color: str = BLUE, filled: bool = True,
           **kwargs) -> ft.Button:
    style = ft.ButtonStyle(
        bgcolor={ft.ControlState.DISABLED: FIELD, ft.ControlState.DEFAULT: color if filled else FIELD},
        color={ft.ControlState.DISABLED: FAINT, ft.ControlState.DEFAULT: "#FFFFFF" if filled else TEXT},
        shape=ft.RoundedRectangleBorder(radius=10), padding=ft.Padding(16, 12, 16, 12),
        text_style=ft.TextStyle(size=13, weight=ft.FontWeight.W_600),
        overlay_color=ft.Colors.with_opacity(0.12, "#FFFFFF"), elevation=0)
    return ft.Button(label, icon=icon, on_click=on_click, style=style, **kwargs)


def icon_button(icon, on_click=None, tooltip: str = "", color: str = MUTED, **kwargs) -> ft.IconButton:
    return ft.IconButton(icon, icon_size=18, icon_color=color, tooltip=tooltip or None,
                         on_click=on_click, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                         **kwargs)


def switch(value: bool, on_change) -> ft.Switch:
    return ft.Switch(value=value, active_color=BLUE, inactive_thumb_color=MUTED, inactive_track_color=HOVER,
                     track_outline_color={ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT},
                     on_change=on_change)


def pill(label: str, color: str = MUTED) -> ft.Container:
    return ft.Container(text(label, 11, color, weight=ft.FontWeight.W_600),
                        padding=ft.Padding(8, 3, 8, 3), border_radius=20,
                        bgcolor=ft.Colors.with_opacity(0.14, color))


def segmented(options: list[tuple[str, str]], value: str, on_change) -> ft.Container:
    """The small pill switcher from the panel headers (Basic / All)."""
    row = ft.Row(spacing=4, tight=True)

    def render(selected):
        row.controls = [
            ft.Container(text(label, 12, TEXT if key == selected else MUTED, weight=ft.FontWeight.W_600),
                         padding=ft.Padding(14, 6, 14, 6), border_radius=8,
                         bgcolor=HOVER if key == selected else None,
                         on_click=lambda e, k=key: pick(k))
            for key, label in options]

    def pick(key):
        render(key)
        row.update()
        on_change(key)

    render(value)
    return ft.Container(row, bgcolor=FIELD, border_radius=10, padding=3)


def numbered(steps: list[str]) -> ft.Column:
    return ft.Column([
        ft.Row([
            ft.Container(text(str(i), 11, BLUE, weight=ft.FontWeight.W_700), width=22, height=22,
                         border_radius=11, alignment=ft.Alignment.CENTER,
                         bgcolor=ft.Colors.with_opacity(0.14, BLUE)),
            text(step, 13, expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START)
        for i, step in enumerate(steps, 1)], spacing=10)
