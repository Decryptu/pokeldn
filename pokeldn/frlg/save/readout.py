"""What a save-dump says to a player: the trainer's IDs from SaveBlock2, the party's natures, IVs and
EVs from SaveBlock1 [decomp:include/global.h:327, 772]. Offsets are into the save block."""
from pokeldn.frlg.rom.rng_countdown import NATURE_NAMES
from pokeldn.frlg.save import mon as monlib
from pokeldn.frlg.text import charmap

SAV1, SAV2 = "sav1", "sav2"
PARTY_COUNT_OFFSET = 0x34
PARTY_OFFSET = 0x38
TRAINER_ID_OFFSET = 0x0A
PLAY_TIME_OFFSET = 0x0E
# IVs word and EVs bytes in the game's stat order; printed in the summary screen's order.
GAME_ORDER = ("HP", "Attack", "Defense", "Speed", "Sp. Atk", "Sp. Def")
SCREEN_ORDER = ("HP", "Attack", "Defense", "Sp. Atk", "Sp. Def", "Speed")


def _substructs(raw):
    """The decrypted, unshuffled 48 bytes as {G, A, E, M}."""
    pid = int.from_bytes(raw[0:4], "little")
    key = pid ^ int.from_bytes(raw[4:8], "little")
    sec = bytearray(raw[32:80])
    for i in range(12):
        v = int.from_bytes(sec[i * 4:i * 4 + 4], "little") ^ key
        sec[i * 4:i * 4 + 4] = (v & 0xFFFFFFFF).to_bytes(4, "little")
    order = monlib.SUBSTRUCT_ORDER[pid % 24]
    return {k: bytes(sec[order.index(k) * 12:][:12]) for k in "GAEM"}


def read_party(data, first_offset):
    """-> [(slot, info or None, why)]; first_offset is where SaveBlock1 0x38 lands in `data`."""
    rows = []
    for slot in range(monlib.PARTY_SIZE):
        start = first_offset + slot * monlib.PARTY_MON_SIZE
        raw = data[start:start + monlib.PARTY_MON_SIZE]
        if len(raw) < monlib.BOX_SIZE:
            rows.append((slot, None, f"only {len(raw)} of 100 bytes in this dump"))
            break
        info = monlib.decode_mon(raw)
        if info is None or info["species"] == 0:
            rows.append((slot, None, "empty"))
            continue
        sub = _substructs(raw)
        ivs_word = int.from_bytes(sub["M"][4:8], "little")
        pid, otid = info["pid"], info["otid"]
        info.update(ivs=dict(zip(GAME_ORDER, ((ivs_word >> (5 * i)) & 31 for i in range(6)))),
                    evs=dict(zip(GAME_ORDER, sub["E"][:6])),
                    is_egg=bool((ivs_word >> 30) & 1),
                    shiny=((otid >> 16) ^ (otid & 0xFFFF) ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8,
                    nature=NATURE_NAMES[pid % len(NATURE_NAMES)],
                    friendship=sub["G"][9], ppbonus=sub["A"][8])
        rows.append((slot, info, None))
    return rows


def trainer(data, *, language=None):
    """SaveBlock2 from offset 0: name, gender, TID, SID and play time."""
    trainer_id = int.from_bytes(data[TRAINER_ID_OFFSET:TRAINER_ID_OFFSET + 4], "little")
    return {"name": charmap.decode(data[0:8], language=language), "gender": "girl" if data[8] else "boy",
            "tid": trainer_id & 0xFFFF, "sid": trainer_id >> 16,
            "hours": int.from_bytes(data[PLAY_TIME_OFFSET:PLAY_TIME_OFFSET + 2], "little"),
            "minutes": data[PLAY_TIME_OFFSET + 2]}


def _stats(values):
    return ", ".join(f"{name} {values[name]}" for name in SCREEN_ORDER)


def describe(block, offset, data, *, language=None):
    """-> plain lines for the log; [] when the dump holds neither the trainer nor the party."""
    if block == SAV2 and offset == 0 and len(data) >= PLAY_TIME_OFFSET + 3:
        who = trainer(data, language=language)
        return [f"Trainer {who['name']} ({who['gender']})",
                f"Trainer ID {who['tid']}, Secret ID {who['sid']}",
                f"Play time {who['hours']}h {who['minutes']:02d}m"]
    party_at = PARTY_OFFSET - offset
    if block != SAV1 or party_at < 0 or party_at >= len(data):
        return []
    lines = []
    if offset <= PARTY_COUNT_OFFSET:
        lines.append(f"Party: {data[PARTY_COUNT_OFFSET - offset]} Pokemon")
    for slot, info, why in read_party(data, party_at):
        if info is None:
            if why != "empty":
                lines.append(f"Slot {slot + 1}: {why}")
            continue
        name = info["species_name"].title()
        head = (f"Slot {slot + 1}: Egg ({name})" if info["is_egg"] else
                f"Slot {slot + 1}: {name}" + (f" \"{info['nickname']}\""
                                              if info["nickname"] and info["nickname"] != info["species_name"]
                                              else "")
                + f", level {info['level']}")
        lines.append(head + f", {info['nature']} nature" + (", shiny" if info["shiny"] else "")
                     + ("" if info["checksum_ok"] else ", damaged record"))
        lines.append(f"  IVs: {_stats(info['ivs'])}")
        lines.append(f"  EVs: {_stats(info['evs'])}")
    return lines
