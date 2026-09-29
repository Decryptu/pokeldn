"""Reads an entry point's own argparse parser, so every flag it accepts can be shown without a copy."""
import argparse
import importlib.util
import os
import sys
from dataclasses import dataclass

from gui.paths import ROOT


@dataclass(frozen=True)
class Flag:
    option: str
    help: str
    kind: str          # "switch", "choice", "value"
    choices: tuple = ()
    default: object = None
    group: str = ""


class _Captured(Exception):
    def __init__(self, parser):
        self.parser = parser


def _load(script: str):
    path = os.path.join(ROOT, script)
    name = f"_pokeldn_entry_{os.path.basename(script)[:-3]}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parser_of(script: str) -> argparse.ArgumentParser:
    module = _load(script)
    if hasattr(module, "build_parser"):
        return module.build_parser()

    # Entry points without build_parser build theirs inside main(); stop main at its first parse.
    def capture(self, *args, **kwargs):
        raise _Captured(self)

    saved = argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args, sys.argv
    argparse.ArgumentParser.parse_args = argparse.ArgumentParser.parse_known_args = capture
    sys.argv = [script]
    try:
        module.main()
    except _Captured as captured:
        return captured.parser
    finally:
        argparse.ArgumentParser.parse_args, argparse.ArgumentParser.parse_known_args, sys.argv = saved
    raise RuntimeError(f"{script} never parsed its arguments")


def flags_of(script: str) -> list[Flag]:
    parser = parser_of(script)
    flags = []
    for group in parser._action_groups:
        for action in group._group_actions:
            if not action.option_strings or isinstance(action, argparse._HelpAction):
                continue
            option = max(action.option_strings, key=len)
            if action.nargs == 0:
                kind = "switch"
            elif action.choices:
                kind = "choice"
            else:
                kind = "value"
            default = None if action.default is argparse.SUPPRESS else action.default
            flags.append(Flag(option, (action.help or "").replace("%%", "%"), kind,
                              tuple(str(c) for c in action.choices or ()), default,
                              "" if group.title in ("options", "optional arguments") else group.title))
    return flags
