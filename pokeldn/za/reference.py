"""The game messages a reference Legends Z-A joiner sends, recorded from an emulated pair whose
player is Player: identity10 on protocol 10; open11, identity11 and identity11b on 11; the 1211-byte selection
record (docs/za.md). identity11b is stored with the joiner's four-byte station prefix.
"""
import os

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
NAMES = ("identity10", "open11", "identity11", "identity11b", "selection")


def load(name, directory=DIR):
    with open(os.path.join(directory, f"{name}.bin"), "rb") as fh:
        return fh.read()
