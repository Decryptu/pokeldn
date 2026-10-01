"""The main screen's size in logical points, so the first window fits it. Flet 1.0 reports none."""
import ctypes
import sys


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _Rect(ctypes.Structure):
    _fields_ = [("origin", _Point), ("size", _Point)]


class _WinRect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def size() -> tuple[float, float] | None:
    """Width and height of the main display in points (macOS) or of the work area without the
    taskbar (Windows, as a DPI-unaware process sees it, which is logical pixels); None elsewhere."""
    try:
        if sys.platform == "darwin":
            cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
            cg.CGMainDisplayID.restype = ctypes.c_uint32
            cg.CGDisplayBounds.restype = _Rect
            cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
            bounds = cg.CGDisplayBounds(cg.CGMainDisplayID())
            return bounds.size.x, bounds.size.y
        if sys.platform == "win32":
            area = _WinRect()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0):   # SPI_GETWORKAREA
                return float(area.right - area.left), float(area.bottom - area.top)
    except (OSError, AttributeError):
        pass
    return None


def fit(wanted: tuple[float, float], minimum: tuple[float, float],
        screen: tuple[float, float] | None) -> tuple[tuple[float, float], tuple[float, float]]:
    """(size, minimum size) for a first window that leaves the menu bar, the Dock or the taskbar
    clear. A screen smaller than the minimum lowers the minimum rather than overflow it."""
    if screen is None:
        screen = (1280.0, 800.0)   # the smallest common laptop screen
    room = (screen[0] - 80, screen[1] - 140)   # macOS menu bar and Dock; Windows title bar
    width, height = min(wanted[0], room[0]), min(wanted[1], room[1])
    return (width, height), (min(minimum[0], width), min(minimum[1], height))
