import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import bdsp_connect
import frlg_mg_host
import frlg_trade_join
import frlg_trade_host
import lgpe_host
import lgpe_join
import pla_host
import swsh_connect
import swsh_gift_host
import swsh_host
import swsh_join
import za_host


def _options(parser):
    return {
        option
        for action in parser._actions
        for option in action.option_strings
    }


def test_readme_options_exist_in_an_entry_point():
    readme = Path("README.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"`(--[a-z][a-z0-9-]*)", readme))
    available = set()
    for module in (frlg_trade_join, frlg_trade_host, frlg_mg_host, lgpe_host, lgpe_join,
                   swsh_connect, swsh_gift_host, swsh_host, swsh_join, bdsp_connect, pla_host,
                   za_host):
        available |= _options(module.build_parser())
    assert documented <= available, sorted(documented - available)


def test_readme_local_links_exist():
    readme = Path("README.md").read_text(encoding="utf-8")
    links = re.findall(r"\[[^]]+\]\((?!https?://)([^)#]+)", readme)
    assert links
    assert all(Path(link).exists() for link in links)


# --- the published site -------------------------------------------------------------------
#
# The sidebar matches `parent` and `grand_parent` against page titles; a mismatch hides the page.

DOCS = Path("docs")
MAX_NAV_DEPTH = 3  # just-the-docs supports title -> parent -> grand_parent and no deeper


def _front_matter(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} has no YAML front matter, so Jekyll serves it raw"
    body = text[4:text.index("\n---\n", 3) + 1]
    fields = {}
    for line in body.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields


def _pages():
    return {path.name: _front_matter(path) for path in sorted(DOCS.glob("*.md"))}


def test_every_page_has_a_title_and_the_titles_are_unique():
    pages = _pages()
    assert pages, "no pages found"
    missing = [name for name, front in pages.items() if not front.get("title")]
    assert not missing, missing
    titles = [front["title"] for front in pages.values()]
    assert len(set(titles)) == len(titles), \
        f"duplicate titles: {sorted({t for t in titles if titles.count(t) > 1})}"


def test_every_parent_names_a_section_page_that_declares_children():
    pages = _pages()
    sections = {front["title"] for front in pages.values() if front.get("has_children") == "true"}
    for name, front in pages.items():
        for key in ("parent", "grand_parent"):
            if key in front:
                assert front[key] in sections, \
                    f"{name}: {key} '{front[key]}' is not the title of any has_children page"


def test_the_navigation_is_a_tree_no_deeper_than_just_the_docs_renders():
    pages = _pages()
    by_title = {front["title"]: front for front in pages.values()}
    for name, front in pages.items():
        depth, node, seen = 1, front, {front["title"]}
        while "parent" in node:
            depth += 1
            assert depth <= MAX_NAV_DEPTH, f"{name} sits {depth} levels deep"
            node = by_title[node["parent"]]
            assert node["title"] not in seen or depth == 2, f"{name} is in a parent cycle"
            seen.add(node["title"])
        # A grandchild must name its grandparent, and name it correctly.
        if depth == 3:
            assert front.get("grand_parent") == by_title[front["parent"]]["parent"], \
                f"{name}: grand_parent does not match its parent's parent"
        else:
            assert "grand_parent" not in front, f"{name} is not a grandchild but sets grand_parent"


def test_every_relative_link_in_the_docs_resolves():
    broken = []
    for path in sorted(DOCS.glob("*.md")):
        for link in re.findall(r"\]\((?!https?://|#)([^)\s]+)", path.read_text(encoding="utf-8")):
            target = link.split("#")[0]
            if target and not (DOCS / target).exists() and not Path(target).exists():
                broken.append(f"{path.name} -> {link}")
    assert not broken, broken


def test_the_site_base_url_matches_the_repository():
    config = (DOCS / "_config.yml").read_text(encoding="utf-8")
    assert "baseurl: /pokeldn" in config
    assert "https://github.com/Decryptu/pokeldn" in config


# --- the launchers ------------------------------------------------------------------------
#
# conftest.py sets sys.path, so launcher imports must be checked in a separate process.

def _standalone(script):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run([sys.executable, script, "--help"],
                          capture_output=True, text=True, env=env, cwd=Path.cwd(), timeout=120)


REPO_MODULES = {"pokeldn", "ldn"} | {
    p.stem for d in ("bin", "tools", "scripts") for p in Path(d).rglob("*.py")
    if "__pycache__" not in str(p)}


@pytest.mark.parametrize("script", sorted(
    str(p) for d in ("bin", "tools", "scripts")
    for p in Path(d).rglob("*.py") if "__pycache__" not in str(p)))
def test_every_launcher_finds_the_package_without_help_from_the_test_harness(script):
    result = _standalone(script)
    missing = re.findall(r"No module named '([\w.]+)'", result.stderr)
    ours = [name for name in missing if name.split(".")[0] in REPO_MODULES]
    assert not ours, \
        f"{script} cannot reach {', '.join(ours)} on its own: " \
        f"{result.stderr.strip().splitlines()[-1]}"
