"""Every program the shipped source starts passes NO_WINDOW (pokeldn/windowless.py) or runs only off Windows."""

import ast
import subprocess
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


def shipped():
    # Tracked files only: gui/client is an ignored Flet checkout holding template sources that do not parse.
    listed = subprocess.run(["git", "ls-files", "-z", "--", *(f"{folder}/*.py" for folder in SHIPPED)],
                            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / name for name in sorted(listed.split("\0")) if name]


def test_every_launch_opens_no_window():
    bare = [f"{path.relative_to(ROOT).as_posix()}:{call.lineno}"
            for path in shipped()
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
