"""Every program pokeldn starts is started with no window on Windows (pokeldn/windowless.py).

pokeldn.exe and its runs are GUI-subsystem, with no console (scripts/pack_app.py): a console program either one
starts without CREATE_NO_WINDOW opens a window of its own, which flashes open and shut. The rule is checked over
the shipped source, not by hand.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ("bin", "pokeldn", "gui")
LAUNCHES = {"run", "Popen", "call", "check_call", "check_output"}
# Linux and macOS commands, started only there: no console window to open.
ELSEWHERE = {"iw", "ip", "ioreg", "open", "pkill", "ditto"}


def _subprocess_launch(node) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr in LAUNCHES
            and isinstance(node.value, ast.Name) and node.value.id == "subprocess")


def launches(tree):
    """subprocess.run(...) and the rest, and calls through a parameter that defaults to one (gui/board.py)."""
    injected = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            positional = node.args.posonlyargs + node.args.args
            defaults = [None] * (len(positional) - len(node.args.defaults)) + node.args.defaults
            pairs = zip(positional + node.args.kwonlyargs, defaults + node.args.kw_defaults)
            injected |= {arg.arg for arg, default in pairs if default is not None and _subprocess_launch(default)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (_subprocess_launch(node.func)
                                           or isinstance(node.func, ast.Name) and node.func.id in injected):
            yield node


def hidden(call: ast.Call) -> bool:
    return any(keyword.arg is None for keyword in call.keywords)      # **NO_WINDOW, or update.py's **_detach()


def elsewhere(call: ast.Call) -> bool:
    first = call.args[0] if call.args else None
    return (isinstance(first, ast.List) and bool(first.elts) and isinstance(first.elts[0], ast.Constant)
            and first.elts[0].value in ELSEWHERE)


def test_every_launch_opens_no_window():
    bare = [f"{path.relative_to(ROOT).as_posix()}:{call.lineno}"
            for folder in SHIPPED for path in sorted((ROOT / folder).rglob("*.py"))
            for call in launches(ast.parse(path.read_text(encoding="utf-8")))
            if not hidden(call) and not elsewhere(call)]
    assert not bare, "pass **NO_WINDOW (pokeldn/windowless.py): " + ", ".join(bare)


def test_the_check_sees_an_injected_launcher_and_a_bare_one():
    tree = ast.parse("import subprocess\n"
                     "def probe(run=subprocess.run):\n"
                     "    run(['powershell'])\n"
                     "    subprocess.Popen(['esptool'])\n"
                     "    subprocess.run(['iw', 'dev'])\n")
    found = [call for call in launches(tree) if not hidden(call) and not elsewhere(call)]
    assert [call.lineno for call in found] == [3, 4]
    
def test_every_file_that_passes_no_window_imports_it():
    missing = [path.relative_to(ROOT).as_posix()
               for folder in SHIPPED for path in sorted((ROOT / folder).rglob("*.py"))
               if "**NO_WINDOW" in (text := path.read_text(encoding="utf-8"))
               and "from pokeldn.windowless import NO_WINDOW" not in text]
    assert not missing, "import NO_WINDOW from pokeldn.windowless: " + ", ".join(missing)