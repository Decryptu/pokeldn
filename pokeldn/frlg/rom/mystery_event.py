"""The Mystery Event VM: the second bytecode the Mystery Gift link can execute, reached through
CLI_RUN_MEVENT_SCRIPT [decomp:src/mystery_event_script.c, data/mystery_event_script_cmd_table.s].

Without `checkcompat` the script runs to its first TRUE-returning command in one pass, and a pointer
operand is an offset into the sent buffer. The status comes back through CLI_LOAD_TOSS_RESPONSE.
docs/frlg_rom.md.
"""

from dataclasses import dataclass, field

# [decomp:data/mystery_event_script_cmd_table.s]
ME_NOP = 0
ME_CHECKCOMPAT = 1
ME_END = 2
ME_SETMSG = 3
ME_SETSTATUS = 4
ME_RUNSCRIPT = 5
ME_INITRAMSCRIPT = 6
ME_SETENIGMABERRY = 7
ME_GIVERIBBON = 8
ME_GIVENATIONALDEX = 9
ME_ADDRAREWORD = 10
ME_SETRECORDMIXINGGIFT = 11
ME_GIVEPOKEMON = 12
ME_ADDTRAINER = 13
ME_ENABLERESETRTC = 14
ME_CHECKSUM = 15
ME_CRC = 16

OPCODE_NAMES = {
    ME_NOP: "nop", ME_CHECKCOMPAT: "checkcompat", ME_END: "end", ME_SETMSG: "setmsg",
    ME_SETSTATUS: "setstatus", ME_RUNSCRIPT: "runscript", ME_INITRAMSCRIPT: "initramscript",
    ME_SETENIGMABERRY: "setenigmaberry", ME_GIVERIBBON: "giveribbon",
    ME_GIVENATIONALDEX: "givenationaldex", ME_ADDRAREWORD: "addrareword",
    ME_SETRECORDMIXINGGIFT: "setrecordmixinggift", ME_GIVEPOKEMON: "givepokemon",
    ME_ADDTRAINER: "addtrainer", ME_ENABLERESETRTC: "enableresetrtc",
    ME_CHECKSUM: "checksum", ME_CRC: "crc",
}

# Handlers returning TRUE: with data[3] == 0 (no checkcompat) nothing after one runs.
TERMINAL_OPCODES = frozenset({
    ME_CHECKCOMPAT, ME_END, ME_SETRECORDMIXINGGIFT, ME_ENABLERESETRTC, ME_CHECKSUM, ME_CRC,
})

# Both call SetIncompatible in FRLG and do nothing else [decomp:src/mystery_event_script.c:227,:291].
DEAD_OPCODES = frozenset({ME_SETRECORDMIXINGGIFT, ME_ENABLERESETRTC})

# client->recvBuffer is AllocZeroed(MG_LINK_BUFFER_SIZE) [decomp:include/mystery_gift_link.h:4].
MAX_SCRIPT_SIZE = 0x400

# Stock statuses in ctx->data[2]; setstatus may write any u8.
STATUS_INCOMPATIBLE = 3         # SetIncompatible, and givepokemon's "party is full"
STATUS_FAILED = 1               # setenigmaberry could not validate; checksum/crc mismatch
STATUS_SUCCESS = 2              # every opcode that did its job

# GiveGiftRibbonToParty accepts index < 11 into a u8[8]; 7..10 write a garbage field
# [decomp:src/pokemon_size_record.c:193].
MAX_RIBBON_INDEX = 6
MAX_RIBBON_ID = 64
MAX_RARE_WORD_ID = 32           # EnableRareWord ignores >= 33 [decomp:src/easy_chat.c:332]

POKEMON_SIZE = 100              # sizeof(struct Pokemon)
MAIL_SIZE = 0x22                # sizeof(struct Mail) [decomp:include/global.h:524]
EREADER_TRAINER_SIZE = 188
ENIGMA_BERRY_ITEM_EFFECT_OFFSET = 0x516     # offsetof(struct ReceivedEnigmaBerry, itemEffect)


class MysteryEventError(Exception):
    """A script that would not do on the console what the caller asked for."""


@dataclass
class Blob:
    """Data placed after the code; its offset from the buffer start is the operand."""
    data: bytes
    align: int = 4
    offset: int | None = field(default=None, compare=False)

    def __len__(self):
        return len(self.data)


def calc_byte_array_sum(data):
    """CalcByteArraySum [decomp:src/util.c:265]: a plain u32 sum of the bytes."""
    return sum(data) & 0xFFFFFFFF


def calc_crc16(data):
    """CalcCRC16 [decomp:src/util.c:231]."""
    crc = 0x1121
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return (~crc) & 0xFFFF


def _u8(value, name, high=0xFF):
    if type(value) is not int or not 0 <= value <= high:
        raise MysteryEventError(f"{name} must be an integer from 0 through {high}")
    return bytes([value])


def _u32(value):
    return int(value).to_bytes(4, "little")


class MysteryEventScript:
    """Emits Mystery Event bytecode; blobs hold data and the assembler resolves their offsets. A
    script must end in a terminal command or the console decodes the rest of its receive buffer."""

    def __init__(self, *, max_size=MAX_SCRIPT_SIZE):
        self.max_size = max_size
        self._code = bytearray()
        self._blobs = []
        self._fixups = []           # (code offset, Blob, extra) -> operand = blob.offset + extra
        self._terminated = False
        self._resumable = False     # only checkcompat sets data[3]


    def blob(self, data, *, align=4):
        handle = Blob(bytes(data), align)
        self._blobs.append(handle)
        return handle


    def _emit(self, opcode, payload=b"", *, refs=()):
        if self._terminated and not self._resumable:
            raise MysteryEventError(
                f"{OPCODE_NAMES[opcode]} follows a terminal command and would never run; "
                "only checkcompat lets execution resume")
        self._code.append(opcode)
        base = len(self._code)
        self._code += payload
        for position, handle, extra in refs:
            self._fixups.append((base + position, handle, extra))
        if opcode in TERMINAL_OPCODES:
            self._terminated = True
            self._resumable = opcode == ME_CHECKCOMPAT
        return self

    def _own(self, handle):
        if not isinstance(handle, Blob):
            raise MysteryEventError("pointer operands take a blob from .blob()")
        if not any(handle is blob for blob in self._blobs):
            raise MysteryEventError("blob belongs to a different script")
        return handle

    def nop(self):
        return self._emit(ME_NOP)

    def end(self):
        return self._emit(ME_END)

    def setstatus(self, value):
        """ctx->data[2] = value; this is what CLI_LOAD_TOSS_RESPONSE ships back to us."""
        return self._emit(ME_SETSTATUS, _u8(value, "status"))

    def setmsg(self, value, text):
        """StringExpandPlaceholders(gStringVar4, text) when value is 0xFF or the status; FRLG's menu
        never displays it."""
        handle = self._own(text)
        return self._emit(ME_SETMSG, _u8(value, "message selector") + _u32(0),
                          refs=((1, handle, 0),))

    def runscript(self, script):
        """RunScriptImmediately on a field script, inside the Mystery Gift menu."""
        handle = self._own(script)
        return self._emit(ME_RUNSCRIPT, _u32(0), refs=((0, handle, 0),))

    def initramscript(self, map_group, map_num, object_id, script):
        """InitRamScript bound to any map and object [decomp:src/mystery_event_script.c:200].
    
        Trap: the Wonder Card then reads as absent until a later card rebinds the slot
        [mystery_gift.c:186]. docs/frlg_gift.md."""
        handle = script if isinstance(script, Blob) else self.blob(script)
        payload = (_u8(map_group, "map group") + _u8(map_num, "map number")
                   + _u8(object_id, "object id") + _u32(0) + _u32(0))
        return self._emit(ME_INITRAMSCRIPT, payload,
                          refs=((3, handle, 0), (7, handle, len(handle))))

    def setenigmaberry(self, berry):
        """SetEnigmaBerry [decomp:src/berry.c:953]; see build_enigma_berry_blob."""
        handle = self._own(berry)
        return self._emit(ME_SETENIGMABERRY, _u32(0), refs=((0, handle, 0),))

    def giveribbon(self, index, ribbon_id):
        """GiveGiftRibbonToParty: ribbon `index` on every non-egg party mon (no ribbon UI in FRLG)."""
        return self._emit(ME_GIVERIBBON,
                          _u8(index, "ribbon index", MAX_RIBBON_INDEX)
                          + _u8(ribbon_id, "ribbon id", MAX_RIBBON_ID))

    def givenationaldex(self):
        return self._emit(ME_GIVENATIONALDEX)

    def addrareword(self, phrase_id):
        return self._emit(ME_ADDRAREWORD, _u8(phrase_id, "rare word id", MAX_RARE_WORD_ID))

    def givepokemon(self, mon):
        """struct Pokemon + struct Mail into party slot 6 [mystery_event_script.c:234]."""
        handle = self._own(mon)
        return self._emit(ME_GIVEPOKEMON, _u32(0), refs=((0, handle, 0),))

    def addtrainer(self, trainer):
        """memcpy into battleTower.ereaderTrainer."""
        handle = self._own(trainer)
        return self._emit(ME_ADDTRAINER, _u32(0), refs=((0, handle, 0),))

    def checksum(self, data, *, expected=None):
        """Terminal. Status unchanged when CalcByteArraySum over the range matches, 1 when not."""
        handle = data if isinstance(data, Blob) else self.blob(data)
        value = calc_byte_array_sum(handle.data) if expected is None else expected
        return self._emit(ME_CHECKSUM, _u32(value) + _u32(0) + _u32(0),
                          refs=((4, handle, 0), (8, handle, len(handle))))

    def crc(self, data, *, expected=None):
        """Terminal, as checksum, but CalcCRC16."""
        handle = data if isinstance(data, Blob) else self.blob(data)
        value = calc_crc16(handle.data) if expected is None else expected
        return self._emit(ME_CRC, _u32(value) + _u32(0) + _u32(0),
                          refs=((4, handle, 0), (8, handle, len(handle))))

    def checkcompat(self, base, language, language2, unk, version):
        """Terminal, but sets data[3] so execution resumes, and data[1] = base for later pointers.
        Unused: LANGUAGE_MASK is the English decomp's value."""
        payload = (_u32(base) + int(language).to_bytes(2, "little") + _u32(language2)
                   + int(unk).to_bytes(2, "little") + _u32(version))
        return self._emit(ME_CHECKCOMPAT, payload)


    def assemble(self):
        if not self._terminated:
            raise MysteryEventError(
                "script has no terminal command; the console would run on into whatever else is "
                "in its receive buffer. End with .end()")
        out = bytearray(self._code)
        for handle in self._blobs:
            padding = -len(out) % handle.align
            out += bytes(padding)
            handle.offset = len(out)
            out += handle.data
        for position, handle, extra in self._fixups:
            out[position:position + 4] = _u32(handle.offset + extra)
        if len(out) > self.max_size:
            raise MysteryEventError(
                f"Mystery Event script is {len(out)} bytes; the console's receive buffer is "
                f"{self.max_size}")
        return bytes(out)


# Operand widths after the opcode byte.
_OPERAND_LAYOUT = {
    ME_NOP: (), ME_END: (), ME_GIVENATIONALDEX: (),
    ME_SETSTATUS: ("u8",), ME_ADDRAREWORD: ("u8",),
    ME_GIVERIBBON: ("u8", "u8"),
    ME_SETMSG: ("u8", "ptr"),
    ME_RUNSCRIPT: ("ptr",), ME_SETENIGMABERRY: ("ptr",), ME_GIVEPOKEMON: ("ptr",),
    ME_ADDTRAINER: ("ptr",),
    ME_INITRAMSCRIPT: ("u8", "u8", "u8", "ptr", "ptr"),
    ME_CHECKSUM: ("u32", "ptr", "ptr"), ME_CRC: ("u32", "ptr", "ptr"),
    ME_CHECKCOMPAT: ("u32", "u16", "u32", "u16", "u32"),
    ME_SETRECORDMIXINGGIFT: (), ME_ENABLERESETRTC: (),
}


def decode(script):
    """Walks the command chain the console would execute, stopping where it would."""
    out = []
    position = 0
    while position < len(script):
        opcode = script[position]
        position += 1
        if opcode not in _OPERAND_LAYOUT:
            out.append((opcode, "?", ()))
            break
        operands = []
        for kind in _OPERAND_LAYOUT[opcode]:
            width = {"u8": 1, "u16": 2, "u32": 4, "ptr": 4}[kind]
            operands.append(int.from_bytes(script[position:position + width], "little"))
            position += width
        out.append((opcode, OPCODE_NAMES[opcode], tuple(operands)))
        if opcode in TERMINAL_OPCODES:
            break
    return tuple(out)


def describe(script):
    parts = []
    for _, name, operands in decode(script):
        parts.append(name if not operands
                     else name + " " + ", ".join(str(value) for value in operands))
    return "; ".join(parts)


@dataclass
class MysteryEventResult:
    status: int
    effects: tuple
    stopped_at: str
    ran: int

    def effect(self, name):
        for entry in self.effects:
            if entry[0] == name:
                return entry
        return None


def run(script, *, party_count=1, enigma_berry_valid=False, buffer_size=MAX_SCRIPT_SIZE):
    """Execute a script as Client_RunMysteryEventScript would, in a zero-padded image of the buffer;
    a read past the buffer is the console's heap and is reported as an effect."""
    image = bytes(script).ljust(buffer_size, b"\x00")
    status = 0
    effects = []
    position = 0
    ran = 0
    stopped_at = "ran off the end of the buffer"

    def read(width):
        nonlocal position
        value = int.from_bytes(image[position:position + width], "little")
        position += width
        return value

    def blob(pointer, size):
        end = pointer + size
        if end > buffer_size:
            effects.append(("read_past_buffer", pointer, size))
        return image[pointer:end]

    while position < buffer_size:
        opcode = image[position]
        position += 1
        if opcode not in _OPERAND_LAYOUT:
            stopped_at = f"unknown opcode {opcode}"
            break
        ran += 1
        name = OPCODE_NAMES[opcode]
        if opcode == ME_NOP:
            pass
        elif opcode == ME_END:
            stopped_at = "end"
            break
        elif opcode == ME_SETSTATUS:
            status = read(1)
        elif opcode == ME_SETMSG:
            selector = read(1)
            pointer = read(4)
            if selector == 0xFF or selector == status:
                effects.append(("setmsg", image[pointer:image.find(b"\xff", pointer) + 1]))
        elif opcode == ME_RUNSCRIPT:
            effects.append(("runscript", read(4)))
        elif opcode == ME_INITRAMSCRIPT:
            map_group, map_num, object_id = read(1), read(1), read(1)
            start, end = read(4), read(4)
            effects.append(("initramscript", map_group, map_num, object_id,
                            blob(start, end - start)))
        elif opcode == ME_SETENIGMABERRY:
            pointer = read(4)
            effects.append(("setenigmaberry", blob(pointer, 28),
                            blob(pointer + ENIGMA_BERRY_ITEM_EFFECT_OFFSET, 20)))
            # SetEnigmaBerry writes a matching checksum, so validity rests on stageDuration and
            # maxYield [decomp:src/berry.c:984].
            berry = blob(pointer, 28)
            status = STATUS_SUCCESS if berry[20] and berry[10] else STATUS_FAILED
        elif opcode == ME_GIVERIBBON:
            effects.append(("giveribbon", read(1), read(1)))
            status = STATUS_SUCCESS
        elif opcode == ME_GIVENATIONALDEX:
            effects.append(("givenationaldex",))
            status = STATUS_SUCCESS
        elif opcode == ME_ADDRAREWORD:
            effects.append(("addrareword", read(1)))
            status = STATUS_SUCCESS
        elif opcode == ME_GIVEPOKEMON:
            pointer = read(4)
            if party_count >= 6:
                effects.append(("givepokemon_full_party",))
                status = STATUS_INCOMPATIBLE
            else:
                effects.append(("givepokemon", blob(pointer, POKEMON_SIZE),
                                blob(pointer + POKEMON_SIZE, MAIL_SIZE)))
                party_count += 1
                status = STATUS_SUCCESS
        elif opcode == ME_ADDTRAINER:
            effects.append(("addtrainer", blob(read(4), EREADER_TRAINER_SIZE)))
            status = STATUS_SUCCESS
        elif opcode in DEAD_OPCODES:
            effects.append(("setincompatible", name))
            status = STATUS_INCOMPATIBLE
            stopped_at = name
            break
        elif opcode in (ME_CHECKSUM, ME_CRC):
            expected = read(4)
            start, end = read(4), read(4)
            data = blob(start, end - start)
            actual = (calc_byte_array_sum(data) if opcode == ME_CHECKSUM
                      else calc_crc16(data))
            if expected != actual:
                status = STATUS_FAILED
                effects.append((name + "_mismatch", expected, actual))
            stopped_at = name
            break
        elif opcode == ME_CHECKCOMPAT:
            stopped_at = "checkcompat"
            effects.append(("checkcompat",))
            break
        else:                                   # pragma: no cover - _OPERAND_LAYOUT is exhaustive
            raise MysteryEventError(f"no runner for opcode {opcode}")

    return MysteryEventResult(status=status, effects=tuple(effects),
                              stopped_at=stopped_at, ran=ran)


def build_enigma_berry_blob(berry, item_effect=b"", hold_effect=0, hold_effect_param=0):
    """Lay a berry out as struct ReceivedEnigmaBerry [decomp:src/berry.c:944]. The effect tail at
    0x516 lies past the 1024-byte buffer, so only the 28-byte Berry2 lands. docs/frlg_rom.md."""
    if len(berry) != 28:
        raise MysteryEventError(f"struct Berry2 is 28 bytes, got {len(berry)}")
    if len(item_effect) > 18:
        raise MysteryEventError("itemEffect is 18 bytes")
    tail = bytes(item_effect).ljust(18, b"\x00") + bytes([hold_effect, hold_effect_param])
    return bytes(berry) + bytes(ENIGMA_BERRY_ITEM_EFFECT_OFFSET - 28) + tail


__all__ = [
    "Blob", "MysteryEventError", "MysteryEventResult", "MysteryEventScript",
    "DEAD_OPCODES", "MAX_SCRIPT_SIZE", "OPCODE_NAMES", "TERMINAL_OPCODES",
    "STATUS_FAILED", "STATUS_INCOMPATIBLE", "STATUS_SUCCESS",
    "build_enigma_berry_blob", "calc_byte_array_sum", "calc_crc16", "decode", "describe", "run",
]
