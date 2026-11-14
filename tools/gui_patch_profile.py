"""Runs the desktop interface with every Flet patch and event logged: one line per patch with its time in ms,
the patched control, the session's control count and the patch's operations, and EVENT lines naming each event (docs/gui.md, Performance).

    POKELDN_GUI_WEB=8813 ./.venv/bin/python tools/gui_patch_profile.py scratchpad/gui_profile/patch.log
"""
import argparse
import os
import runpy
import sys
import time

from flet.controls.base_control import BaseControl
from flet.messaging import session

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log", help="the file the lines are appended to")
    path = parser.parse_args().log
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    log = open(path, "a", buffering=1, encoding="utf-8")
    patch, trigger = session.Session.patch_control, BaseControl._trigger_event
    diff = session.Session._Session__get_update_control_patch
    ops = [0]

    def counted(self, *args, **kwargs):
        result = diff(self, *args, **kwargs)
        ops[0] = len(result[0]) - 1
        return result

    def timed(self, control, *args, **kwargs):
        start = time.perf_counter()
        result = patch(self, control, *args, **kwargs)
        frame, caller = sys._getframe(1), ""
        while frame is not None and not caller:
            if os.sep + "gui" + os.sep in frame.f_code.co_filename:
                caller = f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_lineno} {frame.f_code.co_name}"
            frame = frame.f_back
        log.write(f"{(time.perf_counter() - start) * 1000:.1f} {type(control).__name__} {len(self.index)} "
                  f"ops {ops[0]} {caller}\n")
        return result

    async def named(self, name, data, e=None):
        log.write(f"EVENT {type(self).__name__}.{name}\n")
        return await trigger(self, name, data, e)

    session.Session.patch_control, BaseControl._trigger_event = timed, named
    session.Session._Session__get_update_control_patch = counted
    sys.argv = [os.path.join(ROOT, "gui", "main.py")]
    sys.path[:0] = [os.path.join(ROOT, "gui"), ROOT]
    runpy.run_path(sys.argv[0], run_name="__main__")


if __name__ == "__main__":
    main()
