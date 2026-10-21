"""Save backup and restore over Mystery Gift: the console sends its whole 128 KiB save chip, or writes
one onto it and loads it, through asm/save-backup.s and asm/save-restore.s [docs/frlg_gift.md, Save
backup and restore]. Both servers speak MysteryGiftServer's contract to HostMysteryGiftEngine: run()
publishes ("send", ident, payload, size), ("recv", ident) or ("done", result)."""

import json
import os
import time

from pokeldn.frlg.gift import mg_script
from pokeldn.frlg.gift.mg_server import (
    MysteryGiftServerError, SVR_MSG_CANT_SEND_GIFT_1, SVR_MSG_GIFT_SENT_1, SVR_MSG_NOTHING_SENT,
    _encode_message,
)
from pokeldn.frlg.gift.mystery_gift import (
    MG_LINK_BUFFER_SIZE, MG_LINKID_CLIENT_SCRIPT, MG_LINKID_DYNAMIC_MSG, MG_LINKID_GAME_DATA,
    MG_LINKID_NEWS, MG_LINKID_RAM_SCRIPT, MG_LINKID_READY_END, MG_LINKID_RESPONSE,
)
from pokeldn.frlg.rom import builds
from pokeldn.frlg.rom.buffer_payloads import PAYLOADS
from pokeldn.frlg.save import sav

C = mg_script
BACKUP, RESTORE = "save-backup", "save-restore"

# One pass is three commands of 8 bytes; 32 keeps a client script well inside its 1 KiB buffer.
MAX_PASSES = 32
DECOMPRESSION_BUFFER = 0x0201C000
RESIDENT = DECOMPRESSION_BUFFER + 0x400
RESIDENT_ENTRY = RESIDENT + 4          # asm/save-restore.s 0x004: b entry
OP_DATA, OP_FINISH = 1, 2
DATA_HEADER = 12
SAVE_STATUS_OK = 1                     # LoadGameSave's SAVE_STATUS_OK [include/save.h]
BACKUP_FIRST, BACKUP_SEND_QUEUE = 0x004, 0x008
RESTORE_LOAD_GAME_SAVE = 0x008

BACKED_UP = _encode_message("Your save was copied to\nthe computer.", None)
RESTORED = _encode_message("The save from the computer\nis in. Saving it now.", None)
NOT_RESTORED = _encode_message("The save could not be written.\nNothing was saved.", None)
REFUSED = _encode_message("This save is for another\ncartridge. Nothing changed.", None)


def backup_code(build, first=0):
    code = bytearray(PAYLOADS[BACKUP][0])
    code[BACKUP_FIRST:BACKUP_FIRST + 4] = int(first).to_bytes(4, "little")
    code[BACKUP_SEND_QUEUE:BACKUP_SEND_QUEUE + 4] = build.rfu_send_queue.to_bytes(4, "little")
    return bytes(code)


def restore_code(build):
    code = bytearray(PAYLOADS[RESTORE][0])
    code[RESTORE_LOAD_GAME_SAVE:RESTORE_LOAD_GAME_SAVE + 4] = (build.load_game_save | 1).to_bytes(4, "little")
    return bytes(code)


def _branch_word():
    """`b RESIDENT + 4` from where the client runs a message."""
    return 0xEA000000 | (((RESIDENT_ENTRY - (DECOMPRESSION_BUFFER + 8)) >> 2) & 0xFFFFFF)


def data_messages(sector, raw):
    """-> the OP_DATA messages that fill STAGING with `raw` and write it to `sector`."""
    messages, tokens, offset, i = [], sav.deflate(raw), 0, 0
    while i < len(tokens):
        start, body = offset, bytearray()
        while i < len(tokens) and DATA_HEADER + len(body) + len(tokens[i][0]) <= MG_LINK_BUFFER_SIZE:
            body += tokens[i][0]
            offset += tokens[i][1]
            i += 1
        last = i == len(tokens)
        messages.append(_branch_word().to_bytes(4, "little")
                        + bytes((OP_DATA, sector, 1 if last else 0, 0))
                        + start.to_bytes(2, "little") + len(body).to_bytes(2, "little") + bytes(body))
    return messages


def finish_message():
    return _branch_word().to_bytes(4, "little") + bytes((OP_FINISH,))


def passes_script(count):
    """Receive the image, then `count` passes of LOAD_TOSS_RESPONSE, RUN_BUFFER_SCRIPT, SEND_LOADED."""
    passes = [step for _ in range(count)
              for step in (C.CLI_LOAD_TOSS_RESPONSE, C.CLI_RUN_BUFFER_SCRIPT, C.CLI_SEND_LOADED)]
    return C.client_script((C.CLI_RECV, MG_LINKID_RAM_SCRIPT), *passes,
                           (C.CLI_RECV, MG_LINKID_CLIENT_SCRIPT), C.CLI_COPY_RECV)


def _reporting(ident):
    """Receive one message, run it, send what it pointed the outgoing message at."""
    return [(C.CLI_RECV, ident), C.CLI_LOAD_TOSS_RESPONSE, C.CLI_RUN_BUFFER_SCRIPT, C.CLI_SEND_LOADED,
            (C.CLI_RECV, MG_LINKID_CLIENT_SCRIPT), C.CLI_COPY_RECV]


def console_key(game_data):
    """Which save a partial transfer belongs to: cartridge, trainer id and name."""
    return f"{bytes(game_data.game_code).decode('ascii', 'replace')}-{game_data.trainer_id:08x}"


class _Server:
    """Runs a subclass's _script(), a generator of actions, under the server contract."""

    def __init__(self, *, expect_console=None, progress=None, log=lambda *a: None):
        self.expect_console = None if expect_console is None else str(expect_console).lower()
        self.progress = progress or (lambda done, total: None)
        self.log = log
        self.info = getattr(log, "info", log)
        self.action = None
        self.result = None
        self.game_data = None
        self.build = None
        self.outcome = None            # what the transfer achieved, for the application
        self.messages_sent = self.messages_received = 0
        self.mevent_status = None
        self._reply = None
        self._steps = self._script()

    @property
    def done(self):
        return self.action is not None and self.action[0] == "done"

    def run(self):
        if self.action is None:
            self.action = self._steps.send(self._reply)
            self._reply = None
        return self.action

    def on_sent(self):
        if self.action is None or self.action[0] != "send":
            raise MysteryGiftServerError("on_sent called with no send in flight")
        self.messages_sent += 1
        self.action = None

    def on_received(self, ident, payload):
        if self.action is None or self.action[0] != "recv":
            raise MysteryGiftServerError("on_received called with no recv in flight")
        if ident != self.action[1]:
            raise MysteryGiftServerError(f"expected ident {self.action[1]}, console sent {ident}")
        self.messages_received += 1
        self._reply = bytes(payload)
        self.action = None

    @staticmethod
    def send(ident, payload, size=None):
        return ("send", ident, bytes(payload), len(payload) if size is None else size)

    def _game_data(self):
        """Ask for the console's game data; -> its Build, or None after ending the exchange."""
        yield self.send(MG_LINKID_CLIENT_SCRIPT, C.CLIENT_SCRIPT_SEND_GAME_DATA)
        self.game_data = C.parse_link_game_data((yield ("recv", MG_LINKID_GAME_DATA)))
        self.info("Console identified itself: " + self.game_data.describe())
        refusal = None
        if not C.validate_link_game_data(self.game_data):
            refusal = "its game data failed MysteryGift_ValidateLinkGameData"
        elif self.expect_console and self.game_data.version_name.lower() != self.expect_console:
            refusal = f"this run is for {self.expect_console} and the console runs " \
                      f"{self.game_data.version_name}"
        else:
            try:
                self.build = builds.for_game_code(self.game_data.game_code)
            except builds.UnknownBuild as exc:
                refusal = str(exc)
        if refusal:
            self.outcome = "refused"
            self.info(f"Nothing was read or written: {refusal}.")
            yield self.send(MG_LINKID_CLIENT_SCRIPT, C.CLIENT_SCRIPT_CANT_ACCEPT)
            yield ("recv", MG_LINKID_READY_END)
            self.result = SVR_MSG_CANT_SEND_GIFT_1
            return None
        self.info(f"Console build {self.build.game_code} ({self.build.name}).")
        return self.build

    def _end(self, text, success, result):
        """Show `text`; a success return makes the console save [mystery_gift_menu.c:1379]."""
        yield self.send(MG_LINKID_CLIENT_SCRIPT, C.client_script(
            (C.CLI_RECV, MG_LINKID_DYNAMIC_MSG), C.CLI_COPY_MSG, C.CLI_SEND_READY_END,
            (C.CLI_RETURN, C.CLI_MSG_BUFFER_SUCCESS if success else C.CLI_MSG_BUFFER_FAILURE)))
        yield self.send(MG_LINKID_DYNAMIC_MSG, text)
        yield ("recv", MG_LINKID_READY_END)
        self.result = result

    def _script(self):
        raise NotImplementedError

    def _finished(self):
        while True:
            yield ("done", self.result)


class SaveBackupServer(_Server):
    """Copy the whole chip to the host. A transfer cut short is kept in `resume_dir` by console and
    the next backup of that console goes on from where it stopped."""

    def __init__(self, *, resume_dir=None, **kwargs):
        self.resume_dir = resume_dir
        self.save = None               # the 128 KiB image, once whole
        super().__init__(**kwargs)

    def _partial_path(self):
        return os.path.join(self.resume_dir, console_key(self.game_data) + ".partial")

    def _load_partial(self):
        if not self.resume_dir:
            return bytearray(sav.SAVE_SIZE), 0
        try:
            with open(self._partial_path(), "rb") as handle:
                data = handle.read()
        except OSError:
            return bytearray(sav.SAVE_SIZE), 0
        at = len(data)
        if not 0 < at < sav.SAVE_SIZE:
            return bytearray(sav.SAVE_SIZE), 0
        return bytearray(data.ljust(sav.SAVE_SIZE, b"\x00")), at

    def _keep_partial(self, image, at):
        if not self.resume_dir:
            return
        os.makedirs(self.resume_dir, exist_ok=True)
        path = self._partial_path()
        try:
            if at >= sav.SAVE_SIZE:
                os.remove(path)
            else:
                with open(path + ".tmp", "wb") as handle:
                    handle.write(image[:at])
                os.replace(path + ".tmp", path)
        except OSError:
            pass

    def _script(self):
        build = yield from self._game_data()
        if build is None:
            yield from self._finished()
        image, at = self._load_partial()
        start = at
        if start:
            self.info(f"Going on with this console's backup from {start // 1024} KB.")
        code = backup_code(build, first=start)
        passes = 0
        self.progress(at, sav.SAVE_SIZE)
        while at < sav.SAVE_SIZE:
            # As many passes as the rest should take at the pace so far, and one more.
            count = (min(MAX_PASSES, -(-(sav.SAVE_SIZE - at) * passes // (at - start)) + 1)
                     if passes and at > start else MAX_PASSES)
            yield self.send(MG_LINKID_CLIENT_SCRIPT, passes_script(count))
            yield self.send(MG_LINKID_RAM_SCRIPT, code)
            for _ in range(count):
                tokens = yield ("recv", MG_LINKID_RESPONSE)
                passes += 1
                if at >= sav.SAVE_SIZE:
                    continue        # past the end a pass answers with its 4-byte word
                at = sav.inflate(tokens, image, at)
                self._keep_partial(image, at)
                self.progress(at, sav.SAVE_SIZE)
        self.save = bytes(image)
        summary = sav.describe(self.save)
        self.outcome = "backed-up" if summary.sound else "backed-up-unsound"
        self.info(f"Backup: {sav.SAVE_SIZE // 1024} KB in {passes} passes; "
                  + ("the game's copy is whole." if summary.sound else
                     "NEITHER of the save's two copies is whole."))
        yield from self._end(BACKED_UP, False, SVR_MSG_GIFT_SENT_1)
        yield from self._finished()


class SaveRestoreServer(_Server):
    """Write `save` beside the chip's newest copy, check each sector, then load it; the success
    message makes the game save it [docs/frlg_gift.md, Save backup and restore]."""

    def __init__(self, save, **kwargs):
        self.save = sav.normalize(save)
        self.failed = None
        self.loaded = None
        super().__init__(**kwargs)

    def _script(self):
        build = yield from self._game_data()
        if build is None:
            yield from self._finished()
        try:
            sav.check_restorable(self.save, japanese=build.language == "japanese")
        except sav.SaveError as exc:
            self.outcome = "refused"
            self.info(f"Nothing was written: {exc}.")
            yield from self._end(REFUSED, False, SVR_MSG_NOTHING_SENT)
            yield from self._finished()

        yield self.send(MG_LINKID_CLIENT_SCRIPT, C.client_script(*_reporting(MG_LINKID_RAM_SCRIPT)))
        yield self.send(MG_LINKID_RAM_SCRIPT, restore_code(build))
        footers = yield ("recv", MG_LINKID_RESPONSE)
        newest = sav.chip_newest(footers)
        self.info("The chip's newest copy is " + (f"slot {newest[0]}, counter {newest[1]}"
                                                  if newest else "missing") + ".")
        plan = sav.sectors_to_write(self.save, footers)
        self.progress(0, len(plan))
        for i, (sector, raw) in enumerate(plan):
            messages = data_messages(sector, raw)
            steps = [step for _ in messages[1:] for step in ((C.CLI_RECV, MG_LINKID_NEWS), C.CLI_RUN_BUFFER_SCRIPT)]
            yield self.send(MG_LINKID_CLIENT_SCRIPT, C.client_script(*steps, *_reporting(MG_LINKID_NEWS)))
            for message in messages:
                yield self.send(MG_LINKID_NEWS, message)
            status = yield ("recv", MG_LINKID_RESPONSE)
            failed = int.from_bytes(status[:4], "little")
            if failed:
                self.failed = failed
                self.outcome = "not-restored"
                self.info(f"Sector {sector} did not write (fail mask 0x{failed:08X}); the game keeps "
                          "the save it had.")
                yield from self._end(NOT_RESTORED, False, SVR_MSG_NOTHING_SENT)
                yield from self._finished()
            self.progress(i + 1, len(plan))
        yield self.send(MG_LINKID_CLIENT_SCRIPT, C.client_script(*_reporting(MG_LINKID_NEWS)))
        yield self.send(MG_LINKID_NEWS, finish_message())
        status = yield ("recv", MG_LINKID_RESPONSE)
        self.failed = int.from_bytes(status[:4], "little") if len(status) >= 8 else 0xFFFFFFFF
        self.loaded = status[4] if len(status) >= 8 else 0xFF
        if self.failed == 0 and self.loaded == SAVE_STATUS_OK:
            self.outcome = "restored"
            self.info(f"All {len(plan)} sectors written and read back; the game loaded the save.")
            yield from self._end(RESTORED, True, SVR_MSG_GIFT_SENT_1)
        else:
            self.outcome = "not-restored"
            self.info(f"The game did not load the save (fail mask 0x{self.failed:08X}, load result "
                      f"{self.loaded}); it keeps the save it had.")
            yield from self._end(NOT_RESTORED, False, SVR_MSG_NOTHING_SENT)
        yield from self._finished()


def write_backup(path, server):
    """The backed-up .sav, and beside it the .json the app's library reads [pokeldn/app/saves.py]."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(server.save)
    with open(os.path.splitext(path)[0] + ".json", "w", encoding="utf-8") as handle:
        json.dump({"source": "backup", "created": time.time(),
                   "game_code": bytes(server.game_data.game_code).decode("ascii", "replace")}, handle)
