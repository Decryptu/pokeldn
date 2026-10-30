"""Layout traps in the desktop views that a screenshot shows and no other test catches."""
import ast
from pathlib import Path

import pytest

VIEWS = sorted((Path(__file__).resolve().parent.parent / "gui").glob("**/*.py"))
CONTROLS = {"button", "secondary_button", "icon_button", "switch", "dropdown", "field"}


def _wrapped_at_a_fixed_height(tree: ast.AST):
    """ft.Container(t.<control>(...), height=<number>): a control boxed taller than its field line sits off it
    (the trainer IDs' Find mine sat 7 px low in a 48 px box); t.field_line is the box that lines it up."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Container"
                and node.args and isinstance(node.args[0], ast.Call)):
            continue
        inner = node.args[0].func
        height = next((k.value for k in node.keywords if k.arg == "height"), None)
        if (isinstance(inner, ast.Attribute) and isinstance(inner.value, ast.Name) and inner.value.id == "t"
                and inner.attr in CONTROLS and isinstance(height, ast.Constant)):
            yield node.lineno


@pytest.mark.parametrize("path", [p for p in VIEWS if "client" not in p.parts and "unicorn" not in p.parts],
                         ids=lambda p: p.name)
def test_no_control_is_boxed_at_a_hard_coded_height(path):
    assert list(_wrapped_at_a_fixed_height(ast.parse(path.read_text(encoding="utf-8")))) == []


@pytest.mark.parametrize("kwargs", [{}, {"mono": True, "expand": True}, {"digits": True, "limit": 5}])
def test_a_field_keeps_its_box_when_an_error_comes_and_goes(kwargs):
    """Flet wraps a field that has a height in a SizedBox; adding or dropping it rebuilds the input, which loses
    focus after one typed character (issue 45: the raid seed). An error or helper must leave the box alone."""
    from gui import theme as t
    field = t.field(**kwargs)
    shapes = []
    for details in ({}, {"error": "Eight hexadecimal digits."}, {"helper": "Help."}, {"error": None, "helper": None}):
        for name, value in details.items():
            setattr(field, name, value)
        field.before_update()
        shapes.append((field.height, field.fit_parent_size, field.expand))
    assert len(set(shapes)) == 1
