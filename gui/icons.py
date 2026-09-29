import flet as ft


def icon(name: str, size: int = 18, color: str = "#ECEDEF", **kwargs) -> ft.Image:
    """Pixelarticons 2.4.1, bundled from the free MIT set without changing paths."""
    if size not in (12, 18, 24, 48, 72, 96):
        raise ValueError("Unsupported UI icon size")
    return ft.Image(src=f"icons/{name}.svg", width=size, height=size, color=color,
                    color_blend_mode=ft.BlendMode.SRC_IN, fit=ft.BoxFit.CONTAIN,
                    filter_quality=ft.FilterQuality.NONE, **kwargs)
