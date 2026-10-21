"""The ledger of what the console sends about itself each Mystery Gift session
(`MysteryGiftLinkGameData` [decomp:src/mystery_gift.c:361]). Counters are evidence only as a
difference between sessions of one console; the raw 0x64 bytes are kept for re-parsing."""

import json
from datetime import datetime
from pathlib import Path

from pokeldn.frlg.gift import mg_script
from pokeldn.frlg.text import easychat, easychat_french


def _words(values):
    return [int(value) & 0xFFFF for value in values]


def record(data, *, tag=None, now=None):
    """-> a JSON-shaped dict for one console's `MysteryGiftLinkGameData`."""
    now = now or datetime.now().astimezone()
    return {
        "time": now.isoformat(timespec="seconds"),
        "tag": tag,
        "player_name": data.player_name,
        # None for a full 7-character name, which overwrites the first byte of playerTrainerId
        # [LinkGameData.trainer_id_is_reliable].
        "trainer_id": (data.trainer_id & 0xFFFF) if data.trainer_id_is_reliable else None,
        "version": data.version_name,
        "game_code": data.game_code.decode("ascii", "replace"),
        "software_version": data.software_version,
        "flag_id": data.flag_id,
        "icon_species": data.metadata_icon_species,
        "battles_won": data.battles_won,
        "battles_lost": data.battles_lost,
        "num_trades": data.num_trades,
        "num_stamps": len(data.stamps),
        "max_stamps": data.max_stamps,
        "stamps": [list(stamp) for stamp in data.stamps],
        "questionnaire": _words(data.questionnaire_words),
        "easy_chat_profile": _words(data.easy_chat_profile),
        "raw": data.raw.hex(),
    }


def append(path, data, *, tag=None, now=None):
    """Add one session to the ledger. -> (Path, the record written)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = record(data, tag=tag, now=now)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path, entry


def read(path):
    """-> every record in the ledger, oldest first; a truncated last line is ignored."""
    entries = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return tuple(entries)


def parse_raw(entry):
    """-> the record's bytes back through `parse_link_game_data`, for a question asked later."""
    return mg_script.parse_link_game_data(bytes.fromhex(entry["raw"]))


def console_key(entry):
    """Which console a record came from. The trainer id is absent for a 7-character name, so the
    name and the cartridge are what identify it."""
    return (entry.get("player_name"), entry.get("game_code"), entry.get("version"))


_COUNTERS = (
    ("battles_won", "battles won"),
    ("battles_lost", "battles lost"),
    ("num_trades", "trades"),
    ("num_stamps", "stamps"),
)


def changes(before, after):
    """-> what moved between two records of the same console, as lines. A counter that moves across
    a card change is reported beside the card change."""
    lines = []
    if before.get("flag_id") != after.get("flag_id"):
        lines.append(f"card flagId {before.get('flag_id')} -> {after.get('flag_id')}")
    for key, name in _COUNTERS:
        old, new = before.get(key), after.get(key)
        if old != new:
            lines.append(f"{name} {old} -> {new}")
    if before.get("max_stamps") != after.get("max_stamps"):
        lines.append(f"max stamps {before.get('max_stamps')} -> {after.get('max_stamps')}")
    for key, name in (("questionnaire", "questionnaire"),
                      ("easy_chat_profile", "Easy Chat battle profile")):
        old, new = before.get(key), after.get(key)
        if old != new:
            lines.append(f"{name} {easychat.describe_words(old or ())} "
                         f"-> {easychat.describe_words(new or ())}")
    return tuple(lines)


def language(game_code):
    """-> "french", "english", or None for a cartridge whose Easy Chat table is not here."""
    return {"F": "french", "E": "english"}.get(str(game_code or "")[3:4])


def unknown_words(entry):
    """-> the word ids in this record that no French console has been seen to render."""
    if language(entry.get("game_code")) != "french":
        return ()
    words = tuple(entry.get("questionnaire") or ()) + tuple(entry.get("easy_chat_profile") or ())
    return easychat_french.check(w for w in words if w)


def _describe_words(values, game_code=None):
    # Word 0 is rejected by the console and printed as "???" [IsECWordInvalid,
    # decomp:src/easy_chat.c:118]: an all-zero profile is empty.
    values = [value for value in values or () if value not in (0, easychat.UNDEFINED)]
    if not values:
        return "(none)"
    spoken = language(game_code)
    if spoken == "english":
        return easychat.describe_words(values)
    if spoken == "french":
        return f"{easychat_french.render(values)} [{easychat.describe_words(values)}]"
    return (f"{easychat.describe_words(values)} (no Easy Chat table for {game_code}: the names "
            "are the English decomp's)")


def summary(entries):
    """-> the ledger read back as lines: one block per console, and what changed between its
    sessions. Sessions that changed nothing are counted, not printed."""
    lines = []
    consoles = {}
    for entry in entries:
        consoles.setdefault(console_key(entry), []).append(entry)
    for key, records in consoles.items():
        name, game_code, version = key
        latest = records[-1]
        trainer = ("TID unavailable (7-character name)" if latest.get("trainer_id") is None
                   else f"TID {latest['trainer_id']}")
        lines.append(f"{name!r} ({trainer}) on {version} [{game_code}]: "
                     f"{len(records)} session(s), {records[0]['time']} .. {latest['time']}")
        lines.append(f"  card flagId {latest['flag_id']}, {latest['battles_won']} battles won, "
                     f"{latest['battles_lost']} lost, {latest['num_trades']} trades, "
                     f"{latest['num_stamps']}/{latest['max_stamps']} stamps")
        lines.append("  questionnaire: "
                     + _describe_words(latest.get("questionnaire"), game_code))
        lines.append("  battle profile: "
                     + _describe_words(latest.get("easy_chat_profile"), game_code))
        quiet = 0
        for before, after in zip(records, records[1:]):
            moved = changes(before, after)
            if not moved:
                quiet += 1
                continue
            tag = after.get("tag") or after["time"]
            lines.append(f"  {tag}: " + "; ".join(moved))
        if quiet:
            lines.append(f"  ({quiet} session(s) changed nothing)")
        unknown = unknown_words(latest)
        if unknown:
            lines.append("  never seen rendered in French, worth one question to the player: "
                         + ", ".join(easychat.describe_word(value) for value in unknown))
    return lines
