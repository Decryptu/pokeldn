"""The release notes published with a tag must name the version the tag was cut from."""
from pathlib import Path

from pokeldn import __version__

NOTES = Path(__file__).resolve().parents[1] / ".github" / "release-notes.md"


def test_release_notes_title_is_the_package_version():
    assert NOTES.read_text(encoding="utf-8").splitlines()[0] == f"# pokeldn {__version__}"
