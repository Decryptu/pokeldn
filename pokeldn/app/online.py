"""What the app shows of an online partner, read off the `[online]` lines pokeldn.online.link and the
host launchers print. A line no pattern knows changes nothing."""
import re
from dataclasses import dataclass, replace

OFFER = re.compile(r"^\[online\] (?P<name>.+?) offers (?P<what>.+) \[species (?P<species>\d+)(?P<shiny> shiny)?\]"
                   r"(?: \(PKHeX flags it: (?P<flag>.+)\))?$")
PATTERNS = (
    ("looking", re.compile(r"^\[online\] looking for a partner: [^,]+, (?P<code>.+)$")),
    ("waiting", re.compile(r"^\[online\] (?:waiting for a partner|.*; searching again)$")),
    ("paired", re.compile(r"^\[online\] paired with (?P<name>.+)$")),
    ("withdrew", re.compile(r"^\[online\] .+ took back their offer$")),
    ("confirmed", re.compile(r"^\[online\] .+ confirmed$")),
    ("unconfirmed", re.compile(r"^\[online\] .+ took back their confirmation$")),
    ("refused_theirs", re.compile(r"^\[online\] refused the partner's Pokemon: (?P<why>.+)$")),
    ("refused_ours", re.compile(r"^\[online\] .+'s app refused your Pokemon: (?P<why>.+)$")),
    ("their_done", re.compile(r"^\[online\] .+'s trade \d+ is complete$")),
    ("lost", re.compile(r"^\[online\] (?:lost the partner|the partner left.*|the partner is gone.*)$")),
)
DONE = re.compile(r"^\[done\] trade \d+ complete$")


@dataclass(frozen=True)
class Partner:
    state: str = "looking"       # looking, waiting, paired, lost
    code: str = ""
    name: str = ""
    offer: tuple[int, bool, str] | None = None   # species, shiny, summary
    flag: str = ""               # what PKHeX found wrong with their offer
    confirmed: bool = False
    note: str = ""               # the last refusal, either way
    trades: int = 0


def update(partner: Partner | None, line: str) -> Partner | None:
    """-> the partner after `line`, or None when the line is not about one (and none is known)."""
    line = line.strip()
    if match := OFFER.match(line):
        return replace(partner or Partner(), offer=(int(match["species"]), bool(match["shiny"]), match["what"]),
                       flag=match["flag"] or "", confirmed=False, note="")
    if partner is not None and DONE.match(line):
        return replace(partner, offer=None, flag="", confirmed=False, note="", trades=partner.trades + 1)
    for kind, pattern in PATTERNS:
        match = pattern.match(line)
        if not match:
            continue
        current = partner or Partner()
        if kind == "looking":
            return Partner(code=match["code"])
        if kind == "waiting":
            return replace(current, state="waiting", name="", offer=None, confirmed=False, note="")
        if kind == "paired":
            return replace(current, state="paired", name=match["name"], note="")
        if kind == "withdrew":
            return replace(current, offer=None, flag="", confirmed=False)
        if kind == "confirmed":
            return replace(current, confirmed=True)
        if kind == "unconfirmed":
            return replace(current, confirmed=False)
        if kind == "refused_theirs":
            return replace(current, offer=None, note=f"Their Pokemon was refused: {match['why']}")
        if kind == "refused_ours":
            return replace(current, note=f"Your partner's app refused your Pokemon: {match['why']}. "
                                         "Back out and offer another.")
        if kind == "their_done":
            return current
        if kind == "lost":
            return replace(current, state="lost")
    return partner
