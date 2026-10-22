"""Shared parser types: seeds/PIDs are hexadecimal; counts and trainer IDs are decimal."""
import argparse

from .model import BUILD_CODES, ENCOUNTERS


def hex_word(text):
    try:
        result = int(text.strip(), 16)
        if not 0 <= result <= 0xFFFFFFFF:
            raise ValueError()
        return result
    except ValueError:
        raise argparse.ArgumentTypeError("Expected a 32-bit hexadecimal seed/PID") from None


def ivs(text):
    try:
        result = tuple(int(part.strip()) for part in text.split(","))
        if len(result) != 6 or any(not 0 <= value <= 31 for value in result):
            raise ValueError()
        return result
    except ValueError:
        raise argparse.ArgumentTypeError("Use six IVs (0..31): HP,Atk,Def,SpA,SpD,Spe") from None


def add_common(parser):
    parser.add_argument("--build", choices=BUILD_CODES, default="BPRE")
    parser.add_argument("--encounter", choices=ENCOUNTERS, default="scripted",
                        help="Record label only; all timing profiles are unverified")
    save = parser.add_mutually_exclusive_group()
    save.add_argument("--output", help="Create a new JSON report here; otherwise use the plugin library")
    save.add_argument("--no-save", action="store_true", help="Print the report without writing a file")
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON on stdout")
