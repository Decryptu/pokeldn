"""The field-script command table: one opcode number per command, and the event var ids the
commands take [asm/macros/event.inc, data/script_cmd_table.inc; decomp:src/scrcmd.c].
"""

OP_END = 0x02
OP_RETURN = 0x03
OP_GOTO = 0x05
OP_GOTOSTD = 0x08
OP_CALLSTD = 0x09
OP_COPYBYTE = 0x15
OP_SETVAR = 0x16
OP_ADDVAR = 0x17
OP_SETVAR_OR_COPY = 0x1A
OP_COMPARE_VAR_TO_VALUE = 0x21
OP_SPECIAL = 0x25
OP_SPECIALVAR = 0x26
OP_DELAY = 0x28
OP_SETFLAG = 0x29
OP_CLEARFLAG = 0x2A
OP_CHECKFLAG = 0x2B
OP_PLAYFANFARE = 0x31
OP_GETPLAYERXY = 0x42
OP_GETPARTYSIZE = 0x43
OP_CHECKITEMSPACE = 0x46
OP_FACEPLAYER = 0x5A
OP_WAITMESSAGE = 0x66
OP_CLOSEMESSAGE = 0x68
OP_LOCK = 0x6A
OP_RELEASE = 0x6C
OP_WAITBUTTONPRESS = 0x6D
OP_GIVEMON = 0x79
OP_GIVEEGG = 0x7A
OP_SETMONMOVE = 0x7B
OP_BUFFERNUMBERSTRING = 0x83
OP_CREATEVOBJECT = 0xAA
OP_SETWILDBATTLE = 0xB6
OP_DOWILDBATTLE = 0xB7
OP_SETVADDRESS = 0xB8
OP_VGOTO = 0xB9
OP_VGOTO_IF = 0xBB
OP_VMESSAGE = 0xBD
OP_SETMONMODERNFATEFULENCOUNTER = 0xCD
OP_SETMONMETLOCATION = 0xD2

COMPARE_EQ = 1
COMPARE_NE = 5

VAR_0x8000 = 0x8000
VAR_0x8001 = 0x8001
VAR_0x8002 = 0x8002
VAR_0x8003 = 0x8003
VAR_0x8008 = 0x8008
VAR_PLAYER_X = 0x8004
VAR_PLAYER_Y = 0x8005
VAR_RESULT = 0x800D
VAR_STARTER_MON = 0x4031        # 0 Bulbasaur, 1 Squirtle, 2 Charmander

STD_OBTAIN_ITEM = 0             # gStdScripts index [event_scripts.s:78]

# A saved RAM script runs from a fixed EWRAM address, but vgoto/vmessage operands are relocated
# against this base [setvaddress, src/scrcmd.c].
RAM_SCRIPT_VIRTUAL_BASE = 0x08000000


# Opcodes from scrcmd_names.COMMANDS, operand widths from scrcmd_args.ARGS. docs/frlg_rom.md.

# A linear walk stops at these. `goto` is included because the decomp's labels sit right behind one
# [data/scripts/trainer_battle.inc:17].
TERMINATORS = (OP_END, OP_RETURN, OP_GOTO, OP_GOTOSTD)


def shape(data, base, cursor):
    """-> (name, [(width, value)], length incl. opcode) at `cursor`, or None. A trainerbattle type
    outside scrcmd_args.VARIABLE answers None rather than walk on at a guessed length."""
    from pokeldn.frlg.rom import scrcmd_args, scrcmd_names
    if not 0 <= cursor < len(data):
        return None
    opcode = data[cursor]
    name = scrcmd_names.COMMANDS[opcode] if opcode < scrcmd_names.SCRIPT_CMD_COUNT else "?"

    def read(widths, at):
        operands = []
        for width in widths:
            chunk = data[at:at + width]
            if len(chunk) < width:
                return None, at
            operands.append((width, int.from_bytes(chunk, "little")))
            at += width
        return operands, at

    widths = scrcmd_args.ARGS.get(opcode)
    if widths is not None:
        operands, at = read(widths, cursor + 1)
        return None if operands is None else (name, operands, at - cursor)

    variable = scrcmd_args.VARIABLE.get(opcode)
    if variable is None:
        return None
    head, at = read(variable["head"], cursor + 1)
    if head is None:
        return None
    tail_widths = variable["tails"].get(head[variable["select"]][1])
    if tail_widths is None:
        return None
    tail, at = read(tail_widths, at)
    return None if tail is None else (name, head + tail, at - cursor)


# An operand >= VARS_START is a var reference whatever it names: every ScrCmd body passes its
# arguments through VarGet [decomp:src/event_data.c:235].

# sScriptConditionTable's row order [decomp:src/scrcmd.c:65].
CONDITIONS = ("<", "=", ">", "<=", ">=", "!=")


def name_operand(opcode, index, width, value):
    """-> what an operand means, as text, or None to leave it as a plain number."""
    from pokeldn.frlg.rom import scrcmd_args, scrcmd_names, special_names, symbol_names

    if width == 2 and symbol_names.is_var(value):
        return symbol_names.var_name(value)       # VarGet reads it

    params = scrcmd_args.PARAMS.get(opcode) or ()
    param = params[index] if index < len(params) else None
    if param == "condition" and width == 1 and value < len(CONDITIONS):
        return CONDITIONS[value]
    if param == "function":
        # ScrCmd_special reads a u16 into gSpecials [decomp:src/scrcmd.c:101]; ScrCmd_callstd a u8
        # into gStdScripts. The width says which.
        if width == 2 and value < len(special_names.SPECIALS):
            return special_names.SPECIALS[value]
        if width == 1:
            return f"gStdScripts[{value}]"
    if param == "flag":
        return symbol_names.flag_name(value)
    if param == "type" and opcode in scrcmd_args.VARIABLE:
        return TRAINER_BATTLE_TYPES[value] if value < len(TRAINER_BATTLE_TYPES) else None
    return None


# [decomp:include/constants/battle_setup.h:4], the order the trainerbattle macro branches on.
TRAINER_BATTLE_TYPES = (
    "SINGLE", "CONTINUE_SCRIPT_NO_MUSIC", "CONTINUE_SCRIPT", "SINGLE_NO_INTRO_TEXT", "DOUBLE",
    "REMATCH", "CONTINUE_SCRIPT_DOUBLE", "REMATCH_DOUBLE", "CONTINUE_SCRIPT_DOUBLE_NO_MUSIC",
    "EARLY_RIVAL")


def render_operands(opcode, operands, symbols=True):
    """-> the operands as text: `0xNNNN` always, and what it means beside it when that is known."""
    out = []
    for index, (width, value) in enumerate(operands):
        text = f"0x{value:0{2 * width}X}"
        meaning = name_operand(opcode, index, width, value) if symbols else None
        out.append(f"{text} ({meaning})" if meaning else text)
    return ", ".join(out)


def disassemble(data, base, start=None, limit=64, symbols=False):
    """-> lines of `ADDRESS  opcode  name  operands` for the script at `start` in a dump loaded at
    `base`, stopping at a TERMINATOR, an unmeasurable opcode or the dump's end."""
    from pokeldn.frlg.rom import scrcmd_names
    data = bytes(data)
    cursor = (base if start is None else start) - base
    lines = []
    for _ in range(limit):
        if not 0 <= cursor < len(data):
            lines.append(f"  0x{base + cursor:08X}  (past the end of the dump)")
            break
        opcode = data[cursor]
        measured = shape(data, base, cursor)
        if measured is None:
            from pokeldn.frlg.rom import scrcmd_args
            name = (scrcmd_names.COMMANDS[opcode] if opcode < scrcmd_names.SCRIPT_CMD_COUNT
                    else "?")
            # A known shape running off the end means the dump is short, not that these bytes are no
            # script.
            widths = scrcmd_args.ARGS.get(opcode)
            known = widths is not None or opcode in scrcmd_args.VARIABLE
            why = ("truncated: the dump ends mid-command" if known and
                   cursor + 1 + sum(widths or ()) > len(data)
                   else "no shape here, stopping")
            lines.append(f"  0x{base + cursor:08X}  {opcode:02X}  {name}: {why}")
            break
        name, operands, length = measured
        rendered = render_operands(opcode, operands, symbols)
        lines.append(f"  0x{base + cursor:08X}  {opcode:02X}  {name} " + rendered)
        cursor += length
        if opcode in TERMINATORS:
            break
    return lines


def looks_like_a_script(data, base, start, steps=6):
    """-> whether `steps` instructions decode with known shapes and stay inside the dump."""
    data, cursor = bytes(data), start - base
    for _ in range(steps):
        measured = shape(data, base, cursor)
        if measured is None:
            return False
        if data[cursor] in TERMINATORS:
            return True
        cursor += measured[2]
    return True


class Memory:
    """Several dumps as one address space; overlapping and adjacent segments are merged."""

    def __init__(self, segments):
        merged = []
        for base, data in sorted((int(base), bytes(data)) for base, data in segments):
            if merged and base <= merged[-1][0] + len(merged[-1][1]):
                previous_base, previous = merged[-1]
                overlap = previous_base + len(previous) - base
                if overlap < len(data):
                    merged[-1] = (previous_base, previous + data[overlap:])
            else:
                merged.append((base, data))
        self.segments = merged

    def segment(self, address):
        for base, data in self.segments:
            if base <= address < base + len(data):
                return base, data
        return None

    def __contains__(self, address):
        return self.segment(address) is not None

    def __len__(self):
        return sum(len(data) for _base, data in self.segments)


# Control transfers take the 4-byte `destination` [decomp:src/scrcmd.c:118-176]; `setptrbyte` and
# `copybyte` share the operand name but are memory, so the set is explicit.
JUMPS = {OP_GOTO: "goto", 0x04: "call", 0x06: "goto_if", 0x07: "call_if",
         0xB9: "vgoto", 0xBA: "vcall", 0xBB: "vgoto_if", 0xBC: "vcall_if"}

# Data a script points at but does not execute.
DATA_PARAMS = {"text", "msg", "movements", "products", "ptr", "ptr1", "ptr2", "pointer", "source"}

ROM_START, ROM_END = 0x08000000, 0x0A000000


def follow(data, base, starts=None, limit=64, blocks=256):
    """-> (reached, referenced) for the script(s) at `starts`, chasing every goto and call.

    `data` is a dump with its `base`, or a `Memory` (then `starts` goes second). `reached` is
    {address: disassembly}; `referenced` is {address: {(kind, site)}} for targets not held."""
    from pokeldn.frlg.rom import scrcmd_args
    if isinstance(data, Memory):
        memory, starts = data, base
    else:
        memory, starts = Memory([(base, data)]), starts
    queue = [starts] if isinstance(starts, int) else list(starts)
    reached, referenced = {}, {}
    while queue and len(reached) < blocks:
        address = queue.pop(0)
        if address in reached:
            continue
        found = memory.segment(address)
        if found is None:
            referenced.setdefault(address, set()).add(("entry point", address))
            continue
        segment_base, segment = found
        reached[address] = disassemble(segment, segment_base, address, limit=limit, symbols=True)
        for kind, value, site, is_jump in references(memory, address, limit=limit):
            if is_jump and value in memory:
                queue.append(value)
            elif value not in memory:
                referenced.setdefault(value, set()).add((kind, site))
    return reached, referenced


def references(memory, address, limit=64):
    """-> (kind, value, site, is_jump) for each pointer operand of one block."""
    found = memory.segment(address)
    if found is None:
        return
    from pokeldn.frlg.rom import scrcmd_args
    segment_base, segment = found
    cursor = address - segment_base
    for _ in range(limit):
        measured = shape(segment, segment_base, cursor)
        if measured is None:
            break
        opcode, (_name, operands, length) = segment[cursor], measured
        params = scrcmd_args.PARAMS.get(opcode) or ()
        for index, (_width, value) in enumerate(operands):
            param = params[index] if index < len(params) else None
            is_jump = param == "destination" and opcode in JUMPS
            kind = (JUMPS.get(opcode) if is_jump
                    else param if param in DATA_PARAMS else None)
            if kind is not None and ROM_START <= value < ROM_END:
                yield kind, value, segment_base + cursor, is_jump
        cursor += length
        if opcode in TERMINATORS:
            break


def data_pointers(memory, blocks, limit=64):
    """-> {address: {(kind, site)}} for the data those blocks point at that the memory holds."""
    out = {}
    for block in blocks:
        for kind, value, site, is_jump in references(memory, block, limit=limit):
            if not is_jump and value in memory:
                out.setdefault(value, set()).add((kind, site))
    return out


def read_string(memory, address, limit=1024):
    """-> the game string at `address`, decoded, or None if its 0xFF end is not held."""
    from pokeldn.frlg.text import charmap
    found = memory.segment(address)
    if found is None:
        return None
    base, data = found
    start = address - base
    end = data.find(b"\xff", start, start + limit)
    if end < 0:
        return None
    return charmap.decode_message(data[start:end])


def dump_plan(referenced, window=1024):
    """-> lines naming the `window`-sized `memory-dump` runs covering `referenced`, most addresses
    first."""
    wanted = sorted(referenced)
    windows = {}
    for address in wanted:
        windows.setdefault(address & ~(window - 1), []).append(address)
    lines = []
    for start, addresses in sorted(windows.items(), key=lambda item: (-len(item[1]), item[0])):
        kinds = sorted({kind for address in addresses for kind, _from in referenced[address]})
        lines.append(f"  --dump-address 0x{start:08X} --dump-size {window}   "
                     f"{len(addresses)} address{'es' if len(addresses) > 1 else ''} "
                     f"({', '.join(kinds)})")
    return lines
