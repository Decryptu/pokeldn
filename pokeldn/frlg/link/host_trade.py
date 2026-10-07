"""Leader-side FRLG trade-room engine: tick() returns one parent gSendCmd (seven u16 words),
feed_child_slot() consumes the child's reflected 14-byte row. The leader owns SET_MONS/START/CONFIRM
and every cancel decision, so the follower engine in trade.py cannot be reused with mpid=0."""

from collections import Counter, deque
from dataclasses import dataclass

from pokeldn.frlg.link import battle_link as bl, cable_club, linkplayer, trade, uroom_battle, uroom_chat
from pokeldn.frlg.save import mon as monmod
from pokeldn.gba import block, rfu, rfu_leader


# Deadlock guard only: the console re-sends a fragment until it sees the echo.
ECHO_WAIT_MAX_POLLS = 240
STATUS_REPORT_FRAMES = 30  # 0.5s; the H_LINK_PLAYER stall window is only ~2s
LEAVE_MENU_REPORT_FRAMES = 300
H_LINK_PLAYER = "H_LINK_PLAYER"
H_ENTRY_CARD = "H_ENTRY_CARD"
# Union Room: every choice at the prompt arrives as a SEND_PACKET [union_room.c:2928, :2955].
H_UROOM_PROMPT = "H_UROOM_PROMPT"
# Union Room trading board: one Pokemon block, one mail block, then CB2_LinkTrade
# [union_room.c:1713].
H_UROOM_TRADE = "H_UROOM_TRADE"
# Union Room chat: a JOIN each, one 0x28 block per line, until DISBAND or LEAVE
# [union_room_chat.c:429].
H_UROOM_CHAT = "H_UROOM_CHAT"
# Union Room battle entry [CB2_UnionRoomBattle, CB2_HandleStartBattle battle_main.c:934].
H_UROOM_BATTLE = "H_UROOM_BATTLE"
# The console is master; we answer its controller commands [battle_controllers.c:141].
H_UROOM_BATTLE_LINK = "H_UROOM_BATTLE_LINK"
H_ENTRY_SEAT = "H_ENTRY_SEAT"
# Colosseum: one extra 28-byte LinkPlayer exchange before CB2_InitBattle [cable_club.c:683].
H_CC_BATTLE_ENTRY = "H_CC_BATTLE_ENTRY"
H_PARTY = "H_PARTY"
H_SELECT = "H_SELECT"
H_CONFIRM = "H_CONFIRM"
H_ANIM = "H_ANIM"
H_SAVE = "H_SAVE"
H_LEAVE_MENU = "H_LEAVE_MENU"
H_CANCEL = "H_CANCEL"
H_RETURN_FIELD = "H_RETURN_FIELD"
H_EXIT = "H_EXIT"
H_CLOSE = "H_CLOSE"
H_DONE = "H_DONE"


@dataclass(frozen=True)
class HostTradeTiming:
    # A native trade has six child-initiated standby rounds before BufferTradeParties.
    save_barrier_rounds: int = 6
    # The child repeats the sixth post-save standby after 60 frames until the parent echo completes.
    save_final_standby_quiet_frames: int = 75
    # BufferTradeParties needs a quiet window after the child's first IDLE reaches the host.
    party_link_settle_frames: int = 30
    startup_standby_echo_frames: int = 4
    # A single-VBlank SEND_PLAYER_IDS is missed; the child parks until one is received
    # [decomp:src/link_rfu_2.c:1832].
    player_ids_repeat_frames: int = 8
    # The console may idle waiting for the leader to move first; nothing on the wire reports block
    # consumption. Counted only after our own block has drained.
    link_player_idle_frames: int = 12
    # Longer than SendReadyExitStandbyUntilAllReady's native re-emission cadence.
    entry_final_standby_quiet_frames: int = 75
    # CB2_CreateTradeMenu needs time to install its menu callback.
    final_menu_ready_frames: int = 5 * 60
    post_cancel_exit_wait_frames: int = 5 * 60
    # Keep Pia alive after READY_CLOSE_LINK while the Switch fades and warps.
    post_client_close_grace_frames: int = 15 * 60
    close_retry_frames: int = 60
    # Task_ReceiveChatMessage latches one block per player; back-to-back sends overwrite
    # gBlockRecvBuffer before it reads.
    chat_message_gap_frames: int = 90
    # Fallback for a leaver that stays silent [union_room_chat.c:665]; it is the console's whole
    # wait, so keep it short. A leaver normally answers READY_CLOSE_LINK and 'D' in 0.1s.
    chat_exit_close_frames: int = 120


DEFAULT_HOST_TRADE_TIMING = HostTradeTiming()

SAVE_BARRIER_ROUNDS = DEFAULT_HOST_TRADE_TIMING.save_barrier_rounds
SAVE_FINAL_STANDBY_QUIET_FRAMES = DEFAULT_HOST_TRADE_TIMING.save_final_standby_quiet_frames
PARTY_LINK_SETTLE_FRAMES = DEFAULT_HOST_TRADE_TIMING.party_link_settle_frames
STARTUP_STANDBY_ECHO_FRAMES = DEFAULT_HOST_TRADE_TIMING.startup_standby_echo_frames
PLAYER_IDS_REPEAT_FRAMES = DEFAULT_HOST_TRADE_TIMING.player_ids_repeat_frames
LINK_PLAYER_IDLE_FRAMES = DEFAULT_HOST_TRADE_TIMING.link_player_idle_frames
ENTRY_FINAL_STANDBY_QUIET_FRAMES = DEFAULT_HOST_TRADE_TIMING.entry_final_standby_quiet_frames
FINAL_MENU_READY_FRAMES = DEFAULT_HOST_TRADE_TIMING.final_menu_ready_frames
POST_CANCEL_EXIT_WAIT_FRAMES = DEFAULT_HOST_TRADE_TIMING.post_cancel_exit_wait_frames
POST_CLIENT_CLOSE_GRACE_FRAMES = DEFAULT_HOST_TRADE_TIMING.post_client_close_grace_frames
CLOSE_RETRY_FRAMES = DEFAULT_HOST_TRADE_TIMING.close_retry_frames
CHAT_MESSAGE_GAP_FRAMES = DEFAULT_HOST_TRADE_TIMING.chat_message_gap_frames
CHAT_EXIT_CLOSE_FRAMES = DEFAULT_HOST_TRADE_TIMING.chat_exit_close_frames
HOST_NAME_PAD = linkplayer.HOST_NAME_PAD

# Native leader route to the LEFT trade chair as (LINK_KEY_CODE low byte, held frames); the high
# byte is a rolling heldKeyCount. READY is emitted exactly once, at count 161.
LINK_KEY_EMPTY = 0x11
LINK_KEY_UP = 0x13
LINK_KEY_LEFT = 0x14
LINK_KEY_READY = 0x16
LINK_KEY_EXIT_ROOM = 0x17
ENTRY_LEFT_CHAIR_ROUTE = (
    (LINK_KEY_EMPTY, 43),
    (LINK_KEY_UP, 9),
    (LINK_KEY_EMPTY, 4),
    (LINK_KEY_UP, 14),
    (LINK_KEY_EMPTY, 31),
    (LINK_KEY_LEFT, 5),
    (LINK_KEY_EMPTY, 12),
    (LINK_KEY_UP, 17),
    (LINK_KEY_EMPTY, 25),
    (LINK_KEY_READY, 1),
    (LINK_KEY_EMPTY, 7),
)
# Only the READY key gates the colosseum seat [decomp:src/overworld.c:2989]; the walk is dropped.
# See docs/frlg_link.md.
COLOSSEUM_SPOT_ROUTE = (
    (LINK_KEY_EMPTY, 43),
    (LINK_KEY_READY, 1),
    (LINK_KEY_EMPTY, 7),
)


class HostTradeEngine:
    ECHO_WAIT_MAX_POLLS = ECHO_WAIT_MAX_POLLS
    """Call feed_child_slot(cmd14) for each *new* child UNI command and tick() once per VBlank; after
    disconnect_requested, queue 'D' only after Reliable has delivered the final close-link poll."""

    @property
    def close_confirmed(self):
        return self._close_confirmed

    def __init__(self, party, trade_slot=0, *, offered_slots=None, trades=1,
                 link_player=None, profile=None, anim_delay=1935, trust_pia=True, timing=None,
                 union_room=False, union_room_chat=False, chat_messages=None,
                 union_room_battle=False, battle_forfeit=True, battle_move_slot=0,
                 colosseum=False, card_flag_id=0, log=lambda *a: None):
        self.party = list(party)
        if not 1 <= len(self.party) <= 6:
            raise ValueError("party must contain 1..6 Pokémon")
        if not 1 <= trades <= 6:
            raise ValueError("trades must be 1..6")
        self.trades = trades
        self.offered_slots = trade.resolve_offered_slots(
            offered_slots, trade_slot, trades, party_size=len(self.party))
        if any(i >= len(self.party) for i in self.offered_slots):
            raise ValueError("offered slot exceeds party size")
        if link_player is not None and profile is not None:
            raise ValueError("supply link_player or profile, not both")
        self.lp = (profile.to_link_player() if profile is not None else link_player) \
            or linkplayer.LinkPlayer(name="EMU", version=linkplayer.VERSION_FIRE_RED)
        # The console arms its card counters when this matches its card
        # [decomp:src/union_room.c:1777].
        self.card_flag_id = (profile.card_flag_id if profile is not None else int(card_flag_id))
        self.trainer_card = linkplayer.build_trainer_card(
            self.lp, wonder_card_id=self.card_flag_id,
            mon_species=[m.species for m in self.party],
            name_pad=HOST_NAME_PAD)
        self.anim_delay = anim_delay
        self.trust_pia = trust_pia
        self.union_room = bool(union_room)
        self.union_room_chat = bool(union_room_chat)
        self.union_room_battle = bool(union_room_battle)
        # The cable-club colosseum: the trade-centre entry, then a link battle (cable_club.py).
        self.colosseum = bool(colosseum)
        if self.colosseum and self.union_room:
            raise ValueError("the colosseum is a Direct Corner activity, not a Union Room one")
        if self.union_room_battle and len(self.party) < 2:
            # SetUpPartiesAndStartBattle keeps two mons a side [union_room_battle.c:47]; with one,
            # the battle has nothing to send out second.
            raise ValueError("a Union Room battle needs two party Pokemon; pass a second with "
                             "PARTY2= or --party")
        self.battle_forfeit = bool(battle_forfeit)
        self.battle_move_slot = int(battle_move_slot)
        self.battle = None
        self.echo_backlog = 0  # see _echo_owed
        self.echo_progress = 0
        self.last_echo_cmd = None
        self.echo_emissions = 0  # drops excluded
        self._echo_wait_mark = 0
        self.echo_blocks = []  # pushed by HostSession
        self._child_blocks_landed = 0
        self._echo_wait_block = None
        self._child_slot = None
        self._echo_wait_slot = None
        self._echo_wait_polls = 0
        self._send_history = deque(maxlen=16)
        self._battle_party_block = 0
        self.uroom_requests = []
        self.uroom_trade_request = None
        self.chat_received = []
        self._chat_outbox = deque(uroom_chat.check_text(t) for t in (chat_messages or ()))
        self._chat_joined = False
        self._chat_send_wait = None
        self._chat_exiting = False
        self._last_uroom_packet = None
        self._last_uroom_frame = 0
        self.timing = timing if timing is not None else DEFAULT_HOST_TRADE_TIMING
        self.log = log
        self.info = getattr(log, "info", log)

        self.state = H_LINK_PLAYER
        self.state_history = [self.state]
        self.round = 0
        self.commits = 0
        self.anim_starts = 0
        self.received_mons = []
        self.child_link_player = None
        self.child_card = None
        self.child_party = bytearray(600)
        self.child_cursor = None
        self.done = False
        self.disconnect_requested = False

        self._rx = block.RecvBlock()
        self._words = deque()
        self._blocks = deque()
        self._sender = None
        self._expected = None
        self._party_pair = 0
        self._link_waiting_idle = False
        self._link_idle_frames = 0
        self._link_completed = None
        self._link_player_idle = 0
        self._child_finish = False
        self._anim_wait = None
        self._save_rounds = 0
        self._save_last_count = None
        self._save_final_standby_seen = False
        self._save_standby_quiet = 0
        self._last_child_standby = None
        self._entry_final_standby_seen = False
        self._entry_standby_quiet = 0
        self._exit_count = 0
        self._cancel_standby_count = None
        self._return_standby_count = None
        self._return_standby_quiet = 0
        self._room_exit_wait = None
        self._child_exit_seen = False
        self._leave_menu_wait = None
        self._host_cancel_ready = False
        self._child_cancel_requested = False
        self._close_retry_wait = self.timing.close_retry_frames
        self._close_confirmed = False
        self._close_grace_wait = None
        # Room entry needs a real held-key route; without it the child stays on a black screen.
        self._child_slot_runs = []
        self._child_key_runs = []
        self._held_count = 0
        self._held_plan = deque()
        self._held_steady = None
        self._held_label = None
        self._child_frames = 0
        self._child_idles = 0
        self._child_op_counts = Counter()
        self._child_ops = set()
        self._parent_polls = 0
        self._status_countdown = STATUS_REPORT_FRAMES
        self._leave_menu_run_mark = 0
        self._leave_menu_frame_mark = 0
        self._leave_menu_idle_mark = 0
        self._leave_menu_report = None
        self.trace = []

        # SEND_PLAYER_IDS is idempotent in RfuHandleReceiveCommand.
        for _ in range(self.timing.player_ids_repeat_frames):
            self._queue_words(rfu.send_player_ids_words(), "SEND_PLAYER_IDS")
        self._link_player_block = linkplayer.build_block(
            self.lp, name_pad=HOST_NAME_PAD).ljust(200, b"\x00")
        # Native case 3 emits only the block request [decomp:src/link_rfu_2.c:1852]; our block goes
        # out from _after_child_block.
        self._expected = "link_player"
        self._queue_words(rfu.send_block_req_words(trade.BLOCK_REQ_SIZE_NONE),
                          "BLOCK_REQ:link_player")

    def _report_leave_menu(self):
        frames = self._child_frames - self._leave_menu_frame_mark
        idles = self._child_idles - self._leave_menu_idle_mark
        runs = self._child_slot_runs[self._leave_menu_run_mark:]
        if not runs:
            # A run that started before the mark grows in place: empty means no new run.
            tail = ("no frames at all - the console is off the air"
                    if frames == 0 else
                    f"one unbroken run continuing from before the refresh ({frames} frames)")
        else:
            tail = ", ".join(
                f"{'IDLE' if op is None else rfu.RFUCMD_NAMES.get(op, hex(op))}"
                f"{'' if op is None else f'/{w1:#06x}'}x{n}"
                for (op, w1), n in runs[-8:])
        self.info(
            f"Waiting in H_LEAVE_MENU for the Switch CANCEL; host cancel ready="
            f"{self._host_cancel_ready}, child cancel seen={self._child_cancel_requested}. "
            f"Console has sent since the party refresh: {frames} frames "
            f"({idles} idle): {tail}")

    def _report_status(self):
        ops = ", ".join(
            f"{rfu.RFUCMD_NAMES.get(op, hex(op))}x{count}"
            for op, count in sorted(self._child_op_counts.items(),
                                    key=lambda kv: -kv[1])) or "none"
        self.info(
            f"Waiting in {self.state}: expecting {self._expected!r}, "
            f"console LinkPlayer {'received' if self.child_link_player else 'NOT received'}, "
            f"child frames {self._child_frames} ({self._child_idles} idle) "
            f"vs parent polls {self._parent_polls}, "
            f"queued words {len(self._words)} blocks {len(self._blocks)}, "
            f"opcodes seen: {ops}")

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.state_history.append(state)
            self.trace.append(("state", state))
            self.log(f"host trade: -> {state}")

    def _queue_words(self, words, label):
        self._words.append(list(words))
        self.trace.append(("queue", label))

    def recent_sends(self, n=8):
        """The last few things we put on the wire, newest last."""
        return list(self._send_history)[-n:]

    def _queue_block(self, data, label):
        self._blocks.append((bytes(data), label))
        self.trace.append(("queue_block", label, len(data)))

    def child_route_runs(self):
        return tuple((k, n) for k, n in self._child_key_runs)

    def child_slot_runs(self):
        return tuple((tuple(k), n) for k, n in self._child_slot_runs)

    def format_child_slots(self):
        out = []
        for (op, w1), n in self.child_slot_runs():
            name = "IDLE" if op is None else rfu.RFUCMD_NAMES.get(op, f"0x{op:04x}")
            detail = "" if op is None else f" w1=0x{w1:04x}"
            out.append(f"    {name}{detail} x{n}")
        return "\n".join(out)

    def _set_held_plan(self, runs, label, steady=None):
        self._held_plan.clear()
        for keycode, count in runs:
            self._held_plan.extend([keycode & 0xFF] * max(0, int(count)))
        self._held_steady = None if steady is None else steady & 0xFF
        self._held_label = label
        self.trace.append(("held_plan", label, len(self._held_plan), self._held_steady))

    def _hold_key(self, keycode, label):
        self._set_held_plan(((keycode, 1),), label, steady=LINK_KEY_EMPTY)

    def _start_entry_route(self):
        if self.colosseum:
            self._set_held_plan(COLOSSEUM_SPOT_ROUTE, "COLOSSEUM_SPOT")
            return
        self._set_held_plan(ENTRY_LEFT_CHAIR_ROUTE, "ENTRY_LEFT_CHAIR")

    def _release_key(self, label):
        if self._held_plan or self._held_steady is not None:
            self.trace.append(("release", label))
        self._held_plan.clear()
        self._held_steady = None
        self._held_label = None

    def _next_held_words(self):
        if self._held_plan:
            keycode = self._held_plan.popleft()
        elif self._held_steady is not None:
            keycode = self._held_steady
        else:
            return None
        self._held_count = (self._held_count + 1) & 0xFF
        value = (self._held_count << 8) | keycode
        self.trace.append(("emit_held", self._held_label, value))
        words = rfu.held_keys_words(value)
        # Our EXIT_ROOM must be exposed for one full parent poll before READY_CLOSE_LINK.
        if (keycode == LINK_KEY_EXIT_ROOM and self.state == H_EXIT
                and self._child_exit_seen):
            self._complete_room_exit()
        return words

    def _request_and_send(self, reqtype, data, expected):
        self._expected = expected
        self._queue_words(rfu.send_block_req_words(reqtype), f"BLOCK_REQ:{reqtype}:{expected}")
        self._queue_block(data, f"host:{expected}")

    def _send_linkcmd(self, cmd, cursor=0):
        self._queue_block(trade.linkcmd_block(cmd, cursor), trade.LINKCMD_NAMES[cmd])

    def _enter_cancel_to_leave(self):
        if not (self._host_cancel_ready and self._child_cancel_requested):
            raise RuntimeError("BOTH_CANCEL requires both leader and follower cancel decisions")
        self._set_state(H_CANCEL)
        self._cancel_standby_count = None
        self._return_standby_count = None
        self._return_standby_quiet = 0
        self._room_exit_wait = None
        self._child_exit_seen = False
        self._send_linkcmd(trade.BOTH_CANCEL_TRADE)
        self.info("Switch CANCEL received; both players cancelled. Leaving the trade menu.")

    def _leader_cancel_is_ready(self):
        self._host_cancel_ready = True
        self.trace.append(("leader_cancel_ready",))
        if self._child_cancel_requested:
            self._enter_cancel_to_leave()
        else:
            self.info(
                "Linux host is ready to leave. On the Switch, select CANCEL and confirm YES.")

    def _finish_party_exchange(self):
        self._expected = None
        if self.round >= self.trades:
            self._set_state(H_LEAVE_MENU)
            self._leave_menu_wait = self.timing.final_menu_ready_frames
            self._host_cancel_ready = False
            self._child_cancel_requested = False
            self._leave_menu_run_mark = len(self._child_slot_runs)
            self._leave_menu_frame_mark = self._child_frames
            self._leave_menu_idle_mark = self._child_idles
            self._leave_menu_report = LEAVE_MENU_REPORT_FRAMES
            self.info("Final party refresh complete; waiting 5 seconds for the trade menu.")
        else:
            self._set_state(H_SELECT)

    def _begin_room_exit(self, *, child_already_exited=False):
        self._set_state(H_EXIT)
        self._room_exit_wait = None
        self._child_exit_seen = bool(child_already_exited)
        self._hold_key(LINK_KEY_EXIT_ROOM, "EXIT_ROOM_KEY")
        if child_already_exited:
            self.info("Switch exited the room first; sending the Linux EXIT_ROOM response.")
        else:
            self.info("Five-second room delay complete; leaving the trade room.")

    def _complete_room_exit(self):
        if self.state != H_EXIT:
            return
        self._release_key("EXIT_ROOM_KEY")
        self.trace.append(("child_key", "EXIT_ROOM"))
        self._set_state(H_CLOSE)
        self._close_confirmed = False
        self._close_grace_wait = None
        for _ in range(self.timing.startup_standby_echo_frames):
            self._queue_words(rfu.close_link_words(self._exit_count), "READY_CLOSE_LINK")
        self._close_retry_wait = self.timing.close_retry_frames
        self.info("Both players left the room; closing the RFU link.")

    def _begin_card_exchange(self):
        self._set_state(H_ENTRY_CARD)
        self._request_and_send(trade.BLOCK_REQ_SIZE_100, self.trainer_card, "card")

    def _begin_seated_activity(self):
        """Both players are on their spots [cable_club.c:683]."""
        if self.colosseum:
            self._begin_colosseum_battle()
            return
        self._begin_party_exchange()

    def _begin_colosseum_battle(self):
        """Task_StartWirelessCableClubBattle case 2: the console sends its bare 28-byte LinkPlayer
        unprompted and parks in case 3 until ours lands. Armed from the trainer-card standby: the
        colosseum has no post-seat standby rounds [overworld.c:2989]."""
        self._set_state(H_CC_BATTLE_ENTRY)
        self._expected = "cc_link_player"
        self.info("Colosseum: sending READY for the spot; the console's LinkPlayer record is "
                  "what starts the battle.")

    def _begin_party_exchange(self):
        self._set_state(H_PARTY)
        self.child_party = bytearray(600)
        self._party_pair = 0
        self._request_party_pair()

    def _request_party_pair(self):
        host_party = monmod.party_blocks(monmod.build_player_party(self.party))
        self._request_and_send(trade.BLOCK_REQ_SIZE_200,
                               host_party[self._party_pair], f"party:{self._party_pair}")

    def _after_child_block(self, count, data):
        expected = self._expected
        self.trace.append(("child_block", expected, count))
        expected_count = {
            "link_player": trade.COUNT_PARTY,
            "card": trade.COUNT_TRAINER_CARD,
            "mail": trade.COUNT_MAIL,
            "ribbons": trade.COUNT_RIBBON,
            "uroom_mon": trade.COUNT_TRAINER_CARD,
            "uroom_mail": trade.COUNT_MAIL,
            "uroom_chat": trade.COUNT_RIBBON,
            "battle_accept": uroom_battle.COUNT_ACCEPT,
            "battle_header": uroom_battle.COUNT_HEADER,
            "cc_link_player": cable_club.COUNT_LOCAL,
        }.get(expected, trade.COUNT_PARTY
              if expected and (expected.startswith("party:") or expected.startswith("battle_party:"))
              else None)
        if expected == "battle_link":
            # Link buffer records have no fixed size [PrepareBufferDataTransferLink,
            # battle_controllers.c:412].
            self._on_battle_block(data)
            return
        if expected_count is None:
            self.trace.append(("unexpected_child_block", count))
            return
        if count != expected_count:
            raise ValueError(f"child block count {count}, expected {expected_count} for {expected}")
        if expected == "link_player":
            lp, ok = linkplayer.parse_block(data)
            if not ok:
                # A block predating Task_PlayerExchange case 0 carries stale bytes: too early, not
                # fatal.
                self._rejected_link_players = getattr(self, "_rejected_link_players", 0) + 1
                self.trace.append(("link_player_rejected", self._rejected_link_players))
                self.info("Console LinkPlayer block had an invalid GameFreak magic "
                          f"(#{self._rejected_link_players}); still waiting for a valid one.")
                return
            self.child_link_player = lp
            self._expected = "warp0"
            self._queue_block(self._link_player_block, "host:link_player")
            self.info(f"Console identified as {lp.name!r}; sending the host LinkPlayer block now.")
            return
        if expected == "uroom_chat":
            self._on_chat_block(data)
            return
        if expected == "cc_link_player":
            self._on_colosseum_link_player(data)
            return
        if expected == "battle_accept":
            self._on_battle_accept(data)
            return
        if expected == "battle_header":
            self._on_battle_header(data)
            return
        if expected and expected.startswith("battle_party:"):
            self._on_battle_party(int(expected.split(":", 1)[1]), data)
            return
        if expected == "uroom_mon":
            # Task_StartUnionRoomTrade case 0/1: both sides send their mon unprompted
            # [union_room.c:1721]; ours goes out once theirs is in.
            self.child_party = bytearray(600)
            self.child_party[0:monmod.PARTY_MON_SIZE] = data[:monmod.PARTY_MON_SIZE]
            self.child_cursor = 0
            slot = self.offered_slots[self.round]
            host_party = monmod.build_player_party(self.party)
            self._queue_block(host_party[slot * monmod.PARTY_MON_SIZE:
                                         (slot + 1) * monmod.PARTY_MON_SIZE], "host:uroom_mon")
            self._expected = "uroom_mail"
            self.info("Union Room trade: console Pokemon block received; sending ours, "
                      "mail blocks next.")
            return
        if expected == "uroom_mail":
            # case 2/3: mail both ways, then CB2_LinkTrade; the trade-centre animation path applies.
            self._queue_block(trade.empty_mail_block(), "host:uroom_mail")
            self._expected = None
            self._child_finish = False
            self._set_state(H_ANIM)
            self.anim_starts += 1
            self._anim_wait = self.anim_delay
            self.info("Union Room trade: mail exchanged; the trade animation runs now.")
            return
        if expected == "card":
            self.child_card = bytes(data[:100])
            if self.union_room:
                # No standby follows Task_ExchangeCards in the room [union_room.c:1753].
                self._expected = None
                self._set_state(H_UROOM_PROMPT)
                self.info("Union Room: trainer cards exchanged; waiting at the console's "
                          "'do something' prompt for a SEND_PACKET.")
                return
            self._expected = "warp1"
            return
        if expected and expected.startswith("party:"):
            i = int(expected.split(":", 1)[1])
            self.child_party[i * 200:(i + 1) * 200] = data[:200]
            # BufferTradeParties gates the next request on IsLinkTaskFinished(), not a standby
            # barrier.
            self._link_waiting_idle = True
            self._link_idle_frames = 0
            self._link_completed = f"party:{i}"
            self.trace.append(("party_wait_idle", i))
            self.info(f"Party block {i + 1}/3 exchanged; waiting for the Switch link task to finish.")
            return
        if expected == "mail":
            self._link_waiting_idle = True
            self._link_idle_frames = 0
            self._link_completed = "mail"
            self.trace.append(("mail_wait_idle",))
            self.info("Mail block exchanged; waiting for the Switch link task to finish.")
            return
        if expected == "ribbons":
            self._link_waiting_idle = True
            self._link_idle_frames = 0
            self._link_completed = "ribbons"
            self.trace.append(("ribbons_wait_idle",))
            self.info("Ribbon block exchanged; waiting for the Switch link task to finish.")

    def feed_child_slot(self, slot):
        """Consume one child gSendCmd row (14 bytes, rolling tag permitted)."""
        self._child_slot = rfu_leader._normalize_child_cmd(slot)
        self._child_frames += 1
        is_idle = bytes(slot) == rfu.idle_slot()
        self._record_child_slot_run(slot, is_idle)
        if is_idle:
            self._child_idles += 1
        else:
            self._count_child_op(slot)
        if is_idle:
            self._feed_idle_slot()
            return
        if self.state == H_PARTY and self._link_waiting_idle:
            self._link_idle_frames = 0
        self._link_player_idle = 0
        rec = rfu.parse_slot(slot)
        if rec is None:
            return
        handler = _CHILD_OP_HANDLERS.get(rec["op"])
        if handler is not None:
            handler(self, rec)

    def _record_child_slot_run(self, slot, is_idle):
        _r = None if is_idle else rfu.parse_slot(slot)
        _key = (None, 0) if _r is None else (_r["op"], int.from_bytes(slot[2:4], "little"))
        if self._child_slot_runs and self._child_slot_runs[-1][0] == _key:
            self._child_slot_runs[-1][1] += 1
        else:
            self._child_slot_runs.append([_key, 1])

    def _count_child_op(self, slot):
        _rec = rfu.parse_slot(slot)
        if _rec is not None:
            self._child_op_counts[_rec["op"]] += 1
            if _rec["op"] not in self._child_ops:
                self._child_ops.add(_rec["op"])
                self.info("First console "
                          f"{rfu.RFUCMD_NAMES.get(_rec['op'], hex(_rec['op']))} "
                          f"while host is in {self.state}.")

    def _feed_idle_slot(self):
        if self.state == H_SAVE and self._save_final_standby_seen:
            self._idle_save_final_standby()
            return
        if self.state == H_ENTRY_SEAT and self._entry_final_standby_seen:
            self._idle_entry_final_standby()
            return
        if self.state == H_LINK_PLAYER and self._expected == "warp0":
            self._idle_link_player_wait()
            return
        if self.state == H_PARTY and self._link_waiting_idle:
            self._idle_party_link_settle()

    def _idle_save_final_standby(self):
        self._save_standby_quiet += 1
        if (self._save_standby_quiet
                >= self.timing.save_final_standby_quiet_frames):
            self.trace.append(("save_final_standby_complete",
                               self._save_last_count))
            if self.union_room:
                # CB2_SaveAndEndTrade case 8: the room calls SetCloseLinkCallback instead of another
                # standby [trade_scene.c:2722].
                self.done = True
                self.info("Union Room trade: save barriers complete; the console closes the link "
                          "and returns to the room.")
                return
            self._begin_party_exchange()

    def _idle_entry_final_standby(self):
        self._entry_standby_quiet += 1
        if (self._entry_standby_quiet
                >= self.timing.entry_final_standby_quiet_frames):
            self.trace.append(("entry_final_standby_complete",
                               self._entry_standby_quiet))
            self._expected = None
            self._begin_seated_activity()

    def _idle_link_player_wait(self):
        # tick() drains _words before an in-flight BlockSender: a BLOCK_REQ preempts our block.
        if self._sender is not None or self._blocks:
            return
        self._link_player_idle += 1
        if self._link_player_idle >= self.timing.link_player_idle_frames:
            self.trace.append(("link_player_idle_complete", self._link_player_idle))
            self.info("Console is idle after the LinkPlayer exchange; "
                      "starting the trainer-card exchange.")
            self._begin_card_exchange()

    def _idle_party_link_settle(self):
        self._link_idle_frames += 1
        if self._link_idle_frames >= self.timing.party_link_settle_frames:
            completed = self._link_completed
            self._link_waiting_idle = False
            self._link_completed = None
            if completed and completed.startswith("party:"):
                i = int(completed.split(":", 1)[1])
            else:
                i = None
            if i is not None and i < 2:
                self._party_pair = i + 1
                self.trace.append(("party_link_finished", i))
                self._request_party_pair()
            elif i == 2:
                self.info("Party blocks 3/3 exchanged; exchanging mail and ribbon data.")
                self._request_and_send(
                    trade.BLOCK_REQ_SIZE_220, b"\x00" * 220, "mail")
            elif completed == "mail":
                self._request_and_send(
                    trade.BLOCK_REQ_SIZE_40, b"\x00" * 40, "ribbons")
            elif completed == "ribbons":
                self._finish_party_exchange()

    def _child_send_block_init(self, rec):
        self._rx.on_init(rec["count"], rec.get("owner_raw"))

    def _child_send_block(self, rec):
        was_done = self._rx.done
        self._rx.on_block(rec["index"], rec["frag"])
        if self._rx.done and not was_done:
            data, count = self._rx.data(), self._rx.count
            self._rx.consume()
            self._on_child_block(count, data)

    def _child_send_held_keys(self, rec):
        key = rec.get("keycode", 0) & 0xFF
        if self._child_key_runs and self._child_key_runs[-1][0] == key:
            self._child_key_runs[-1][1] += 1
        else:
            self._child_key_runs.append([key, 1])
        if key == LINK_KEY_READY and self.state == H_ENTRY_SEAT:
            self.trace.append(("child_key", "READY"))
            self._maybe_finish_entry()
        elif key == LINK_KEY_EXIT_ROOM and self.state in (H_RETURN_FIELD, H_CC_BATTLE_ENTRY,
                                                          H_UROOM_BATTLE_LINK):
            # After a colosseum battle the console waits for every player to reach EXITING_ROOM
            # [KeyInterCB_WaitForPlayersToExit, overworld.c:2977]; unanswered, the link errors.
            self.trace.append(("child_exit_first",))
            self._begin_room_exit(child_already_exited=True)
        elif key == LINK_KEY_EXIT_ROOM and self.state == H_EXIT:
            self._child_exit_seen = True
            self._complete_room_exit()

    def _child_ready_exit_standby(self, rec):
        self._on_child_standby(rec.get("count", 0))

    # Union Room activity words [include/constants/union_room.h]
    UR_IN_ROOM = 0x40
    UR_CARD = 0x48        # ACTIVITY_CARD, "Salut": show each other's trainer card
    UR_BATTLE = 0x41      # ACTIVITY_BATTLE_SINGLE | IN_UNION_ROOM
    UR_TRADE = 0x44       # ACTIVITY_TRADE | IN_UNION_ROOM, from the trading board
    UR_CHAT = 0x45        # ACTIVITY_CHAT | IN_UNION_ROOM
    UR_ACCEPT = 0x51      # ACTIVITY_ACCEPT | IN_UNION_ROOM
    UR_DECLINE = 0x52     # ACTIVITY_DECLINE | IN_UNION_ROOM
    UR_PACKET_REPEAT = 3  # read every frame; a few repeats are safe

    def _child_send_packet(self, rec):
        """UR_STATE_HANDLE_ACTIVITY_REQUEST [union_room.c:3151]: ACCEPT or DECLINE, SEND_PACKET."""
        packet = rec.get("packet") or [0] * 6
        request = packet[0]
        if not self.union_room or request == 0:
            return
        if self.state not in (H_ENTRY_CARD, H_UROOM_PROMPT):
            self.trace.append(("uroom_packet_ignored", self.state, request))
            return
        key = tuple(packet)
        # Guards only a packet echoed in consecutive frames; the same choice made later is a new
        # request.
        if key == self._last_uroom_packet and self._child_frames - self._last_uroom_frame <= 4:
            return
        self._last_uroom_packet = key
        self._last_uroom_frame = self._child_frames
        self.uroom_requests.append(key)
        self._set_state(H_UROOM_PROMPT)
        if request == self.UR_CARD:
            reply, what = self.UR_ACCEPT, "greetings (trainer cards); accepting, a standby barrier follows"
        elif request == self.UR_TRADE:
            reply = self.UR_ACCEPT
            what = (f"a trade from the trading board (it offers species {packet[1]} level "
                    f"{packet[2]}); accepting. It sends its Pokemon block after a standby barrier")
            self.uroom_trade_request = (packet[1], packet[2])
            self._set_state(H_UROOM_TRADE)
            self._expected = "uroom_mon"
        elif request == self.UR_CHAT and self.union_room_chat:
            reply = self.UR_ACCEPT
            what = ("a chat; accepting. A standby barrier follows, then both members SendBlock a "
                    "JOIN and the console opens its chat keyboard")
            self._set_state(H_UROOM_CHAT)
            self._expected = "uroom_chat"
        elif request == self.UR_BATTLE and self.union_room_battle:
            reply = self.UR_ACCEPT
            what = ("a battle; accepting. It picks two mons, then both sides send a 0x20 selection "
                    "block and the link battle starts")
            self._set_state(H_UROOM_BATTLE)
            self._expected = "battle_accept"
        elif request in (self.UR_BATTLE, self.UR_CHAT):
            reply, what = self.UR_DECLINE, "a battle or chat; declining, the console closes the link"
        elif request == self.UR_IN_ROOM:
            self.trace.append(("uroom_exit", key))
            self.info("Union Room: the console chose Exit; it closes the link now.")
            return
        else:
            reply, what = self.UR_DECLINE, f"an unknown activity 0x{request:02x}; declining"
        self.trace.append(("uroom_reply", request, reply))
        for _ in range(self.UR_PACKET_REPEAT):
            self._queue_words(rfu.send_packet_words([reply]), f"UROOM_PACKET:{reply:#04x}")
        self.info(f"Union Room: the console asked for {what}.")

    def _child_ready_close_link(self, rec):
        if self.union_room and self.state not in (H_CLOSE, H_DONE):
            # Exit or decline: the console waits for every player's READY_CLOSE_LINK
            # [WaitAllReadyToCloseLink, link_rfu_2.c:1471] before it disconnects.
            self._set_state(H_CLOSE)
            self._close_confirmed = False
            self._close_grace_wait = None
            for _ in range(self.timing.startup_standby_echo_frames):
                self._queue_words(rfu.close_link_words(self._exit_count), "READY_CLOSE_LINK")
            self._close_retry_wait = self.timing.close_retry_frames
            self.info("Union Room: the console is closing the link; sending our READY_CLOSE_LINK.")
        if self.state != H_CLOSE:
            return
        self.trace.append(("child_close_ready", rec.get("count", 0)))
        if not self._close_confirmed:
            self._close_confirmed = True
            if not self._chat_exiting:
                # The chat leaver is parked on !gReceivedRemoteLinkPlayers: keep the grace short.
                self._close_grace_wait = self.timing.post_client_close_grace_frames
            self.trace.append(("child_close_confirmed",
                               rec.get("count", 0),
                               self.timing.post_client_close_grace_frames))
            self.info(
                "Switch confirmed it left the chat; closing now."
                if self._chat_exiting else
                "Switch confirmed it left the trade room; keeping peer traffic active "
                f"for {self.timing.post_client_close_grace_frames / 60:g} seconds before "
                "disconnecting.")

    def _on_child_block(self, count, data):
        self._child_blocks_landed += 1
        # A 4-byte-payload battle record is 16 bytes, exactly COUNT_LINKCMD: in a battle the state
        # decides the path, not the size.
        if count == trade.COUNT_LINKCMD and self.state != H_UROOM_BATTLE_LINK:
            self._on_child_linkcmd(int.from_bytes(data[:2], "little"),
                                   int.from_bytes(data[2:4], "little"))
        else:
            self._after_child_block(count, data)

    def _on_child_standby(self, count):
        if self.state == H_PARTY:
            # Late room-entry standby traffic can overlap BufferTradeParties but is not its gate.
            self._link_idle_frames = 0
            return
        # A one-VBlank barrier echo can be missed, leaving the child repeating its count forever;
        # save/cancel barriers are multi-round and keep a single echo.
        repeats = (self.timing.startup_standby_echo_frames
                   if self.state in (H_LINK_PLAYER, H_ENTRY_CARD, H_ENTRY_SEAT,
                                     H_UROOM_PROMPT, H_UROOM_TRADE, H_UROOM_CHAT,
                                     H_UROOM_BATTLE, H_UROOM_BATTLE_LINK, H_CC_BATTLE_ENTRY,
                                     H_CANCEL, H_RETURN_FIELD)
                   else 1)
        for _ in range(repeats):
            self._queue_words(rfu.exit_standby_words(count), f"STANDBY:{count}")
        self._last_child_standby = count
        self._exit_count = max(self._exit_count, count + 1)
        if self.state == H_LINK_PLAYER and self._expected == "warp0":
            self._begin_card_exchange()
        elif self.state == H_ENTRY_CARD and self._expected == "warp1":
            if self.colosseum:
                # The colosseum has no post-seat standbys; the console parks in
                # Task_StartWirelessCableClubBattle case 3 [cable_club.c:706]. Its block ends the
                # entry.
                self._begin_colosseum_battle()
                self._start_entry_route()
                return
            self._set_state(H_ENTRY_SEAT)
            self._expected = "warp2"
            self._start_entry_route()
        elif self.state == H_ENTRY_SEAT:
            if count >= 3:
                self._entry_standby_quiet = 0
            self._maybe_finish_entry()
        elif self.state == H_SAVE:
            if self._save_last_count is None:
                self._save_last_count = count
                self._save_rounds = 1
            elif count == self._save_last_count:
                pass
            elif count == ((self._save_last_count + 1) & 0xFFFF):
                self._save_last_count = count
                self._save_rounds += 1
            else:
                self.trace.append(("save_standby_out_of_sequence",
                                   self._save_last_count, count))
            if self._save_rounds >= self.timing.save_barrier_rounds:
                self._save_standby_quiet = 0
                if not self._save_final_standby_seen:
                    self._save_final_standby_seen = True
                    self.trace.append(("save_final_standby_seen", count))
                    self.info(
                        "Save barriers complete; waiting for the Switch menu handoff to finish.")
        elif self.state == H_CANCEL:
            if self._cancel_standby_count is None:
                self._cancel_standby_count = count
            elif count == ((self._cancel_standby_count + 1) & 0xFFFF):
                # The next child-initiated count proves the cancel barrier passed.
                self._set_state(H_RETURN_FIELD)
                self._return_standby_count = count
                self._room_exit_wait = self.timing.post_cancel_exit_wait_frames
                self.trace.append(("cancel_standby_complete",
                                   self._cancel_standby_count, count))
                self.info("Trade menu closed; waiting 5 seconds before Linux exits the room.")
        elif self.state == H_RETURN_FIELD:
            self._return_standby_count = count

    def _maybe_finish_entry(self):
        if (self.state == H_ENTRY_SEAT and self._last_child_standby is not None
                and self._last_child_standby >= 3):
            self._release_key("COLOSSEUM_SPOT" if self.colosseum else "ENTRY_LEFT_CHAIR")
            self._entry_final_standby_seen = True
            self._entry_standby_quiet = 0
            self.trace.append(("entry_final_standby_seen", self._last_child_standby))

    def _on_child_linkcmd(self, cmd, cursor):
        self.trace.append(("child_linkcmd", trade.LINKCMD_NAMES.get(cmd, hex(cmd)), cursor))
        if cmd == trade.READY_TO_TRADE and self.state == H_SELECT:
            self.child_cursor = cursor % 6
            self._set_state(H_CONFIRM)
            self._send_linkcmd(trade.SET_MONS_TO_TRADE, self.offered_slots[self.round])
        elif cmd == trade.INIT_BLOCK and self.state == H_CONFIRM:
            self._set_state(H_ANIM)
            self.anim_starts += 1
            self._anim_wait = self.anim_delay
            self._send_linkcmd(trade.START_TRADE)
        elif cmd == trade.READY_FINISH_TRADE and self.state == H_ANIM:
            self._child_finish = True
        elif cmd == trade.REQUEST_CANCEL and self.state == H_SELECT:
            # The leader cancels too: BOTH_CANCEL_TRADE [trade.c:1715-1722] ends the session on the
            # player's first Cancel, as every other title's host lets a player back out at once.
            self._host_cancel_ready = True
            self._child_cancel_requested = True
            self.trace.append(("both_cancel_at_select",))
            self._enter_cancel_to_leave()
        elif cmd == trade.REQUEST_CANCEL and self.state == H_LEAVE_MENU:
            # The follower sends it from its live menu and waits on "waiting for friend" until
            # BOTH_CANCEL [trade.c:2049, 1643]; a native leader that chose CANCEL answers at once
            # [trade.c:1715-1722], so the menu wait no longer applies.
            self._child_cancel_requested = True
            self.trace.append(("child_cancel_requested",))
            self._leave_menu_wait = None
            self._host_cancel_ready = True
            self._enter_cancel_to_leave()
        elif cmd in (trade.READY_TO_TRADE, trade.READY_CANCEL_TRADE) \
                and self.state == H_LEAVE_MENU:
            # Native sends PLAYER_CANCEL when the leader chose CANCEL but the follower picked a mon.
            self._send_linkcmd(trade.PLAYER_CANCEL_TRADE)
            self.trace.append(("reject_extra_trade", trade.LINKCMD_NAMES.get(cmd, hex(cmd))))
            self.info(
                "Switch selected another trade; Linux declined it. Dismiss the message, then "
                "select CANCEL and confirm YES to leave.")

    def incoming_mon(self):
        """The console's chosen Pokemon, the one `_commit` takes, or None before it chose."""
        if self.child_cursor is None:
            return None
        off = self.child_cursor * monmod.PARTY_MON_SIZE
        return monmod.Mon(bytes(self.child_party[off:off + monmod.PARTY_MON_SIZE]))

    def _commit(self):
        host_slot = self.offered_slots[self.round]
        child_slot = self.child_cursor
        received = self.incoming_mon()
        if received is None:
            raise RuntimeError("cannot commit without child selection")
        self.received_mons.append(received)
        self.party[host_slot] = received
        self.round += 1
        self.commits += 1
        self.trace.append(("commit", self.commits, host_slot, child_slot))
        self._send_linkcmd(trade.CONFIRM_FINISH_TRADE)
        self._set_state(H_SAVE)
        self._save_rounds = 0
        self._save_last_count = None
        self._save_final_standby_seen = False
        self._save_standby_quiet = 0
        self._child_finish = False
        self._anim_wait = None

    def tick(self):
        """One VBlank -> the parent's seven-word gSendCmd row."""
        self._parent_polls += 1
        if self.state == H_LINK_PLAYER:
            self._tick_status_report()
        if self.state == H_LEAVE_MENU:
            self._tick_leave_menu()
        if self.state == H_RETURN_FIELD and self._room_exit_wait is not None:
            self._tick_room_exit_wait()
        if self.state == H_CLOSE and not self.disconnect_requested:
            self._tick_close_link()
        if self.state == H_ANIM and self._anim_wait is not None:
            self._tick_anim()
        if self.state == H_UROOM_CHAT:
            self._tick_chat_exit() if self._chat_exiting else self._tick_chat_outbox()
        return self._next_parent_words()

    def _on_colosseum_link_player(self, data):
        """Task_StartWirelessCableClubBattle case 2/3 [cable_club.c:701]: the bare 28-byte
        LinkPlayer, no GameFreak magics. The console's card counter records our trainerId [cable_club.c:794]."""
        lp = cable_club.read_local_link_player(data)
        self.child_link_player = lp
        self._queue_block(cable_club.local_link_player_block(self.lp, name_pad=HOST_NAME_PAD),
                          "host:cc_link_player")
        self._expected = "battle_header"
        self.info(f"Colosseum: console LinkPlayer {lp.name!r} on its spot; sending ours as "
                  f"trainer id 0x{self.lp.trainer_id & 0xFFFFFFFF:08x}. The battler header is next.")

    def _on_battle_accept(self, data):
        """CB2_UnionRoomBattle case 3/4 [union_room_battle.c:139]: the console sends its 0x51 block
        first, so we answer rather than lead."""
        if not uroom_battle.read_accept_block(data):
            self.info("Union Room battle: the console backed out of its party selection; it closes "
                      "the link now.")
            self._expected = None
            self._set_state(H_UROOM_PROMPT)
            return
        self._queue_block(uroom_battle.accept_block(), "host:battle_accept")
        self._expected = "battle_header"
        self.info("Union Room battle: the console picked its two Pokemon; sending our accept. "
                  "Two link standbys, then the battler header.")

    @property
    def _battle_tag(self):
        return "Colosseum" if self.colosseum else "Union Room battle"

    def _battle_mons(self):
        """Two chosen mons in the Union Room [union_room_battle.c:47]; the whole party otherwise."""
        return list(self.party) if self.colosseum else self.party[:2]

    def _on_battle_header(self, data):
        """CB2_HandleStartBattle state 1/2 [battle_main.c:962]; version 0x200 makes the console
        master [:886]."""
        version = data[0] | (data[1] << 8)
        mons = self._battle_mons()
        self._queue_block(uroom_battle.battler_header(party_count=len(mons)), "host:battle_header")
        self._battle_party_block = 0
        self._expected = "battle_party:0"
        self.info(f"{self._battle_tag}: console version signature 0x{version:03x}; sending ours as "
                  f"0x{uroom_battle.VERSION_NON_MASTER:03x} so it takes the master role. "
                  "Three party blocks next.")

    def _on_battle_party(self, i, data):
        """States 3/7/11: the party two slots at a time. In the Union Room only the first block
        carries mons [union_room_battle.c:51]."""
        self.child_party[i * 200:(i + 1) * 200] = data[:200]
        mons = self._battle_mons()
        blocks = uroom_battle.party_blocks(mons, limit=6 if self.colosseum else 2)
        self._queue_block(blocks[i], f"host:battle_party:{i}")
        if i + 1 < uroom_battle.PARTY_BLOCK_COUNT:
            self._expected = f"battle_party:{i + 1}"
            self.info(f"{self._battle_tag}: party block {i + 1}/3 exchanged.")
            return
        self._expected = "battle_link"
        self._set_state(H_UROOM_BATTLE_LINK)
        self.battle = uroom_battle.BattleController(
            mons, multiplayer_id=0, forfeit=self.battle_forfeit,
            move_slot=self.battle_move_slot, log=self.info)
        self.info(f"{self._battle_tag}: parties exchanged; the console is master and drives the "
                  "battle from here. " + ("We forfeit at the first action prompt."
                                          if self.battle_forfeit else "We fight."))

    def _on_battle_block(self, data):
        """One link buffer record; every BUFFER_A command is acked [battle_util.c:185]."""
        rec = bl.parse(data)
        # The console sets the exec-flag bit our answer clears only once it sees this slot returned.
        # See _echo_owed.
        self._echo_wait_slot = self._child_slot
        self._echo_wait_mark = self.echo_emissions
        self._echo_wait_block = self._child_blocks_landed - 1
        self._echo_wait_polls = 0
        self.trace.append(("battle_recv", rec["buffer_id"], rec["active_battler"], rec["cmd"]))
        self.info(f"{self._battle_tag}: <- {bl.describe(rec)}")
        for out in self.battle.feed(data):
            self._queue_block(out, f"host:battle:{bl.describe(bl.parse(out))}")
        if self.battle.done:
            self._expected = None
            self.info(f"{self._battle_tag}: over; waiting for the console to close the "
                      "link.")

    def _on_chat_block(self, data):
        """One inbound 0x28 chat block; members send unprompted for the chat's life
        [union_room_chat.c:1451]."""
        msg = uroom_chat.parse(data)
        self.chat_received.append(msg)
        self.trace.append(("uroom_chat_recv", msg["cmd"], msg["name"]))
        self.info(f"Union Room chat: {uroom_chat.describe(msg)}")
        if msg["cmd"] == uroom_chat.JOIN and not self._chat_joined:
            self._chat_joined = True
            self._queue_block(uroom_chat.build(uroom_chat.JOIN, self.lp.name, multiplayer_id=0),
                              "host:chat_join")
            self._chat_send_wait = self.timing.chat_message_gap_frames
            self.info("Union Room chat: sending our JOIN; the console lists us as a member.")
        elif msg["cmd"] in (uroom_chat.LEAVE, uroom_chat.DROP, uroom_chat.DISBAND):
            self._begin_chat_exit()

    def _begin_chat_exit(self):
        """Task_ReceiveChatMessage case 4 [union_room_chat.c:1524]: the leader sends DROP, then
        SetCloseLinkCallback [:665]. The leaver does nothing until we do."""
        if self._chat_exiting:
            return
        self._chat_exiting = True
        self._chat_send_wait = None
        self._chat_outbox.clear()
        self._queue_block(uroom_chat.build(uroom_chat.DROP, self.lp.name, multiplayer_id=0),
                          "host:chat_drop")
        self.info("Union Room chat: the console left the chat; sending our DROP, then closing "
                  "the link it is waiting on.")

    def queue_chat_message(self, text):
        """Add a line to a live chat; False once the chat is over or has not opened."""
        if self.state != H_UROOM_CHAT or self._chat_exiting or not self._chat_joined:
            return False
        self._chat_outbox.append(uroom_chat.check_text(text))
        if self._chat_send_wait is None:
            self._chat_send_wait = 0
        return True

    def _tick_chat_exit(self):
        """Hold until our DROP has drained, then close with a short grace of our own: the leaver is
        already waiting for the link to go."""
        if self._sender is not None or self._blocks or self._words:
            return
        self._set_state(H_CLOSE)
        self._close_confirmed = False
        self._close_grace_wait = self.timing.chat_exit_close_frames
        for _ in range(self.timing.startup_standby_echo_frames):
            self._queue_words(rfu.close_link_words(self._exit_count), "READY_CLOSE_LINK")
        self._close_retry_wait = self.timing.close_retry_frames
        self.trace.append(("chat_exit_close", self._exit_count))
        self.info("Union Room chat: our DROP is out; closing the RFU link, which is what the "
                  "console is waiting for.")

    def _tick_chat_outbox(self):
        """One queued line at a time, spaced (see CHAT_MESSAGE_GAP_FRAMES). None when drained or the
        chat has not opened."""
        if self._chat_send_wait is None or self._sender is not None or self._blocks:
            return
        if self._chat_send_wait > 0:
            self._chat_send_wait -= 1
            return
        if not self._chat_outbox:
            self._chat_send_wait = None
            self.info("Union Room chat: every queued line has been sent; the chat stays open "
                      "until the console leaves it.")
            return
        text = self._chat_outbox.popleft()
        self._queue_block(uroom_chat.build(uroom_chat.CHAT, self.lp.name, text=text),
                          "host:chat_msg")
        self._chat_send_wait = self.timing.chat_message_gap_frames
        self.trace.append(("uroom_chat_send", text))
        self.info(f"Union Room chat: sending {text!r}.")

    def _tick_status_report(self):
        self._status_countdown -= 1
        if self._status_countdown <= 0:
            self._status_countdown = STATUS_REPORT_FRAMES
            self._report_status()

    def _tick_leave_menu(self):
        if self._leave_menu_report is not None:
            self._leave_menu_report -= 1
            if self._leave_menu_report <= 0:
                self._leave_menu_report = LEAVE_MENU_REPORT_FRAMES
                self._report_leave_menu()
        if self.state == H_LEAVE_MENU and self._leave_menu_wait is not None:
            self._leave_menu_wait -= 1
            if self._leave_menu_wait <= 0:
                self._leave_menu_wait = None
                self._leader_cancel_is_ready()

    def _tick_room_exit_wait(self):
        self._room_exit_wait -= 1
        # Counted in child polls: it stretches when the console's poll rate drops.
        if self._room_exit_wait % 60 == 0 and self._room_exit_wait > 0:
            done = self.timing.post_cancel_exit_wait_frames - self._room_exit_wait
            self.info(
                f"Room-exit buffer {done}/{self.timing.post_cancel_exit_wait_frames} frames; "
                f"still waiting before leaving.")
        if self._room_exit_wait <= 0:
            self._begin_room_exit()

    def _tick_close_link(self):
        if self._close_grace_wait is not None:
            self._close_grace_wait -= 1
            if self._close_grace_wait <= 0:
                self._close_grace_wait = None
                self.disconnect_requested = True
                self.trace.append(("close_grace_complete",))
                self.info("Room-exit grace complete; closing the RFU session.")
        self._close_retry_wait -= 1
        if self._close_retry_wait <= 0:
            for _ in range(self.timing.startup_standby_echo_frames):
                self._queue_words(rfu.close_link_words(self._exit_count), "READY_CLOSE_LINK")
            self._close_retry_wait = self.timing.close_retry_frames

    def _tick_anim(self):
        if self._anim_wait > 0:
            self._anim_wait -= 1
        elif self._child_finish:
            self._commit()

    def _echo_owed(self):
        """Never answer a battle command before the console's block is echoed back
        (docs/frlg_link.md). Neither an empty queue (5-8 s per command), an echo count (ECHO_MAX drops
        fragments) nor the last fragment's content (blocks share tails) is enough."""
        if self.state != H_UROOM_BATTLE_LINK or self._echo_wait_slot is None:
            return False
        if self._echo_block_returned():
            self._echo_wait_slot = None
            return False
        self._echo_wait_polls += 1
        if self._echo_wait_polls > self.ECHO_WAIT_MAX_POLLS:
            self.info("Union Room battle: the console never took back its own last fragment after "
                      f"{self._echo_wait_polls} polls; answering anyway. If it stalls here, that "
                      "wait is the thing to look at.")
            self._echo_wait_slot = None
            return False
        return True

    def _echo_block_returned(self):
        """Every fragment index of the console's block has been echoed at least once. Trap: an echo
        of a re-sent fragment sharing a frame with our ack is read after the ack."""
        k = self._echo_wait_block
        if k is None or k >= len(self.echo_blocks):
            return False
        rec = self.echo_blocks[k]
        count = rec.get("count") or 0
        return count > 0 and set(range(count)) <= rec["indices"]

    def _next_parent_words(self):
        if self._words:
            return self._words.popleft()
        held_words = self._next_held_words()
        if held_words is not None:
            return held_words
        if self._sender is None and self._blocks and not self._echo_owed():
            data, label = self._blocks.popleft()
            self._sender = block.BlockSender(data, owner=0, trust_pia=self.trust_pia)
            self.trace.append(("send_block", label, len(data)))
            self._send_history.append(f"{self._parent_polls}: block {label} ({len(data)} B)")
        if self._sender is not None:
            words = self._sender.tick(None)
            if self._sender.done:
                self._sender = None
            return words
        return [0] * 7

    @property
    def established(self):
        return self.child_link_player is not None

    def mark_disconnect_sent(self):
        """The engine cannot declare success before the close-link poll and 'D' enter Reliable."""
        if not self.disconnect_requested:
            raise RuntimeError("disconnect sent before close-link handshake")
        self.done = True
        self._set_state(H_DONE)


_CHILD_OP_HANDLERS = {
    rfu.SEND_BLOCK_INIT: HostTradeEngine._child_send_block_init,
    rfu.SEND_BLOCK: HostTradeEngine._child_send_block,
    rfu.SEND_HELD_KEYS: HostTradeEngine._child_send_held_keys,
    rfu.READY_EXIT_STANDBY: HostTradeEngine._child_ready_exit_standby,
    rfu.READY_CLOSE_LINK: HostTradeEngine._child_ready_close_link,
    rfu.SEND_PACKET: HostTradeEngine._child_send_packet,
}