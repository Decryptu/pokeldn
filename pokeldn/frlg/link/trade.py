"""Joiner trade FSM: a reactive Follower that supplies blocks on SEND_BLOCK_REQ, pushes LINKCMD
blocks and reacts to SET_MONS -> START -> CONFIRM_FINISH; it never emits Leader broadcasts
[trade.c:1637-1666]. By REQ size: 200 LinkPlayerBlock then party, 100 card, 220 mail, 40 ribbons."""

from pokeldn.frlg.link import linkplayer
from pokeldn.frlg.save import mon as monmod
from pokeldn.gba import barrier as barriermod, block, rfu

# LINKCMD opcodes (ride as word0 of a 20-byte/count=2 block).
READY_TO_TRADE = 0xAABB         # OUT
SET_MONS_TO_TRADE = 0xDDDD      # IN
INIT_BLOCK = 0xBBBB             # OUT (confirm-YES)
START_TRADE = 0xCCDD            # IN
READY_FINISH_TRADE = 0xABCD     # OUT
CONFIRM_FINISH_TRADE = 0xDCBA   # IN
REQUEST_CANCEL = 0xEEAA         # OUT
READY_CANCEL_TRADE = 0xBBCC     # OUT
PLAYER_CANCEL_TRADE = 0xDDEE    # IN
BOTH_CANCEL_TRADE = 0xEEBB      # IN
PARTNER_CANCEL_TRADE = 0xEECC   # IN
LINKCMD_NAMES = {v: k for k, v in dict(
    READY_TO_TRADE=READY_TO_TRADE, SET_MONS_TO_TRADE=SET_MONS_TO_TRADE, INIT_BLOCK=INIT_BLOCK,
    START_TRADE=START_TRADE, READY_FINISH_TRADE=READY_FINISH_TRADE,
    CONFIRM_FINISH_TRADE=CONFIRM_FINISH_TRADE, REQUEST_CANCEL=REQUEST_CANCEL,
    READY_CANCEL_TRADE=READY_CANCEL_TRADE, PLAYER_CANCEL_TRADE=PLAYER_CANCEL_TRADE,
    BOTH_CANCEL_TRADE=BOTH_CANCEL_TRADE, PARTNER_CANCEL_TRADE=PARTNER_CANCEL_TRADE).items()}

PARTY_SIZE = 6
# Block counts (= ceil(size/12)) used to classify a completed peer-0 block.
COUNT_LINKCMD = 2
COUNT_PARTY = 17
COUNT_MAIL = 19         # fixed 220B mail buffer
COUNT_RIBBON = 4        # fixed 40B giftRibbons buffer

# A cleared struct Mail is not all-zero (ClearMailStruct: 0xFFFF words, EOS name, BULBASAUR);
# BufferTradeParties sends six 34-byte records plus four bytes through the 220-byte request.
MAIL_STRUCT_SIZE = 34
MAIL_COUNT = 6


def empty_mail_block():
    record = (b"\xff" * 18       # words[9]
              + b"\xff" * 8     # playerName[8]
              + b"\x00" * 4     # trainerId[4]
              + b"\x01\x00"     # SPECIES_BULBASAUR
              + b"\x00\x00")    # ITEM_NONE
    assert len(record) == MAIL_STRUCT_SIZE
    payload = record * MAIL_COUNT
    return payload.ljust(220, b"\x00")

# CheckValidityOfTradeMons return values [include/constants/trade.h:31-34].
PLAYER_MON_INVALID = 0          # our selected mon is the last alive mon
BOTH_MONS_VALID = 1
PARTNER_MON_INVALID = 2         # host offered an (illegitimate) Deoxys/Mew

# CheckValidityOfTradeMons refuses a Deoxys/Mew without the fateful-encounter flag [trade.c:1966];
# the flag is not decodable offline, so refusing any offered Deoxys/Mew is opt-in.
SPECIES_MEW = 151
SPECIES_DEOXYS = 410

# DoTradeAnim_Wireless stand-in: START_TRADE -> READY_FINISH measured 32.4 s, about 1935 frames; the
# early-arrival guard keeps the FSM correct for any value.
DEFAULT_ANIM_FRAMES = 1935

# QueueAction(180) delay before READY_CANCEL_TRADE on an invalid-mon verdict [trade.c:1989/2000].
INVALID_CANCEL_DELAY = 180

S1_LINK, S4_PARTY, S5_SELECT, S6_CONFIRM, S7_ANIM, S8_DONE, S_CANCEL = \
    "S1_LINK", "S4_PARTY", "S5_SELECT", "S6_CONFIRM", "S7_ANIM", "S8_DONE", "S_CANCEL"

# Child-initiated standby points [link_rfu_2.c:1566-1573]: (b) menu->scene seam [trade.c:2159-2166],
# (c) post-trade save chain [trade_scene.c:2566-2725], (d) cancel-exit [trade.c:2117-2132]. A
# strict-ROM host waits in the leader branch for the child at each.

# BLOCK_REQ_* [include/link.h:111-115]: word0 low byte of a SEND_BLOCK_REQ, sizes our reply
# [link.c:185-190; link_rfu_2.c:1172-1173].
BLOCK_REQ_SIZE_NONE = 0     # identical to 200
BLOCK_REQ_SIZE_200 = 1      # LinkPlayer / party blocks
BLOCK_REQ_SIZE_100 = 2      # trainer card (Task_ExchangeCards entry pull)
BLOCK_REQ_SIZE_220 = 3      # mail
BLOCK_REQ_SIZE_40 = 4       # giftRibbons
REQ_SIZE = {BLOCK_REQ_SIZE_NONE: 200, BLOCK_REQ_SIZE_200: 200, BLOCK_REQ_SIZE_100: 100,
            BLOCK_REQ_SIZE_220: 220, BLOCK_REQ_SIZE_40: 40}

# The native child emits each READY_EXIT_STANDBY round once and idles; Pia reliable retransmits it.
# Repeating keeps the host in a completed round, and a flood jams the reliable window.
WARP_STANDBY_EMITS = 1

# After both sit the child drives two more standby rounds (count=2, 3) before the host pulls the
# party; the delay lets our READY go out first.
POST_SEAT_STANDBY_DELAY = 20

# Post-seat standby is mutual: advance count=2 -> 3 only after the host reached count=2, else its
# readyExitStandby FSM desyncs (in-game comms error). WARP4_WATCHDOG is the offline backstop only.
WARP4_WATCHDOG = 180

# The host paces save barriers by its LinkFullSave writes; bursting the next round races its save
# FSM. Only the first round's host wait [case 100] has a 180f timeout.
SAVE_BARRIER_GAP = 60
# ENTRY_BARRIER_GAP: entry warp barriers re-arm on emitted slots and the leader goes silent while it
# waits, so the gap is short (the save chain keeps 60: there the host echoes).
HOST_WALK_QUIET_FRAMES = 20  # host held-key frames with no DPAD code before we treat it as parked
SEAT_HOST_READY_MAX = 1200  # ~20s safety bound on waiting for the host to reach its chair
ENTRY_BARRIER_GAP = 6
# After count=3 the native child idles ~75 slots and the leader pulls the party off that run, so a
# fresh count=3 is spaced wider.
POST_SEAT_REARM_GAP = 90
# 0 = unpaced. Pacing compounds with the credit pacer and the LinkPlayer exchange has a tight
# budget; do not re-tune this against a single run.
JOINER_STREAM_GAP = 0

# The host pauses up to 1.8 s between save barriers; the chain ends on host re-exchange (Phase M),
# this only releases a vanished host.
SAVE_CHAIN_TIMEOUT = 600

# Last-resort ribbons fallback. Must exceed the host's 0.3-1.8 s save-write pauses between block
# pulls, else the cancel-to-leave fires before its mail/ribbons and both sides deadlock.
BUFFERTRADE_SETTLE = 600
# After a PARTNER/PLAYER_CANCEL_TRADE both sides return to the trade menu [trade.c:2094-2113] and
# the leader waits for both to select afresh; stands in for the A-press dismissing the message.
RESELECT_DELAY = 60

COUNT_TRAINER_CARD = 9      # ceil(100/12)

# Entry phases, one-shot per session [trade_scene.c:2752]: P0 standby [union_room.c:1975-2013], P1
# card pull [union_room.c:1753-1789], P2 seat [cable_club.c:827-868], P3 standby
# [cable_club.c:910-942], P4 trade menu [trade.c:826], P5 the trade FSM owns the link.
P0_WARP_QUIESCE_1 = "P0_WARP_QUIESCE_1"
P1_CARD_EXCHANGE = "P1_CARD_EXCHANGE"
P2_SEAT_BARRIER = "P2_SEAT_BARRIER"
P3_WARP_QUIESCE_2 = "P3_WARP_QUIESCE_2"
P4_TRADE_MENU = "P4_TRADE_MENU"
P5_IN_TRADE = "P5_IN_TRADE"
ENTRY_PHASES = (P0_WARP_QUIESCE_1, P1_CARD_EXCHANGE, P2_SEAT_BARRIER,
                P3_WARP_QUIESCE_2, P4_TRADE_MENU, P5_IN_TRADE)

# Leader-only broadcasts the Follower must never emit [trade.c:1637-1672].
LEADER_BROADCAST_OPCODES = frozenset((
    SET_MONS_TO_TRADE, START_TRADE, CONFIRM_FINISH_TRADE,
    PLAYER_CANCEL_TRADE, BOTH_CANCEL_TRADE, PARTNER_CANCEL_TRADE))


def linkcmd_block(cmd, cursor=0):
    return (cmd & 0xFFFF).to_bytes(2, "little") + (cursor & 0xFFFF).to_bytes(2, "little") \
        + b"\x00" * 16


def resolve_offered_slots(offered_slots, trade_slot, trades, party_size=None):
    """Slots must be distinct: TradeMons swaps the received mon into the offered slot
    [trade_scene.c:1054-1083], so re-offering one would give away a just-received mon."""
    if offered_slots is not None:
        slots = list(offered_slots)
        if len(slots) != trades:
            raise ValueError(f"offered_slots must have {trades} entries, got {len(slots)}")
        if any(s < 0 for s in slots):
            raise ValueError(f"offered_slots must be non-negative, got {slots}")
        if len(set(slots)) != len(slots):
            raise ValueError(f"offered_slots must be distinct (no slot re-offered), got {slots}")
        return slots
    seeded = [trade_slot + i for i in range(trades)]
    if party_size is not None and any(s >= party_size for s in seeded):
        return list(range(trades))      # full-party-swap default (trade_slot left default)
    return seeded


class EntryPhase:
    """Monotonic record of the entry phases P0..P5; generates no traffic. P1 only if the card pull
    is observed."""

    def __init__(self, log=lambda *a: None):
        self.phase = P0_WARP_QUIESCE_1
        self.phase_history = [P0_WARP_QUIESCE_1]
        self.card_pulled = False
        self.card_supplied = False
        self.host_card = None
        # Latches at P4: Task_StartWirelessTrade case 0 clears the keys callback [cable_club.c:918]
        # before CB2_CreateTradeMenu, so held keys stop before any party traffic.
        self.seat_phase_over = False
        self.complete = False
        self.log = log
        self.info = getattr(log, "info", log)

    def _advance_to(self, phase):
        if ENTRY_PHASES.index(phase) <= ENTRY_PHASES.index(self.phase):
            return
        cur = ENTRY_PHASES.index(self.phase)
        for p in ENTRY_PHASES[cur + 1:ENTRY_PHASES.index(phase) + 1]:
            self.phase = p
            self.phase_history.append(p)
            self.log(f"entry: -> {p}")
        if ENTRY_PHASES.index(phase) >= ENTRY_PHASES.index(P4_TRADE_MENU):
            self.seat_phase_over = True
        if phase == P5_IN_TRADE:
            self.complete = True

    def on_card_req(self):
        if self.complete:
            return
        if not self.card_pulled:
            self.card_pulled = True
            self.log("entry: host pulled BLOCK_REQ_SIZE_100 (trainer card)")
        self._advance_to(P1_CARD_EXCHANGE)

    def on_card_supplied(self):
        if not self.complete:
            self.card_supplied = True

    def on_host_card(self, data100):
        """Cosmetic; does not advance the trade FSM [union_room.c:1769-1779]."""
        if self.complete:
            return
        self.host_card = bytes(data100[:100])
        self._advance_to(P1_CARD_EXCHANGE)
        self.log("entry: received host trainer card (100B) -> recvBuffer[0]")
        self.info("Exchanged trainer cards.")

    def on_seat_reached(self):
        """Does NOT latch seat_phase_over (that is P4)."""
        if not self.complete:
            self._advance_to(P2_SEAT_BARRIER)

    def on_trade_menu_open(self):
        """Latches seat_phase_over without completing the entry (P5 is the first mon selection)."""
        self._advance_to(P4_TRADE_MENU)

    def on_trade_menu_live(self):
        self._advance_to(P5_IN_TRADE)


class TradeEngine:
    def __init__(self, party, trade_slot=1, link_player=None,
                 anim_delay=None, mpid=1, decline=False, refuse_partner_deoxys_mew=False,
                 trades=1, offered_slots=None, trust_pia=False, log=lambda *a: None):
        """mpid must be 1 (the Follower, right seat). Each round replays exchange -> select ->
        confirm -> anim -> commit; after the last, cancel-to-leave."""
        assert mpid == 1, f"sim must be the RIGHT-seat Follower (mpId==1), got mpId={mpid}"
        self.party = list(party)
        self.trade_slot = trade_slot
        self.mpid = mpid
        # Chair1 [data/scripts/cable_club.inc:644-649]; no emitted byte may depend on it.
        self.cosmetic_seat = 1
        self.lp = link_player or linkplayer.LinkPlayer()
        self.anim_delay = DEFAULT_ANIM_FRAMES if anim_delay is None else anim_delay
        self.decline = decline
        self.refuse_partner_deoxys_mew = refuse_partner_deoxys_mew
        # trust_pia: fire-and-forget fragments relying on Pia's reliable layer (see block.py).
        self.trust_pia = trust_pia
        self.log = log
        self.info = getattr(log, "info", log)

        if not 1 <= trades <= 6:
            raise ValueError(f"trades must be 1..6, got {trades}")
        self.trades = trades
        self.offered_slots = resolve_offered_slots(offered_slots, trade_slot, trades,
                                                   party_size=len(self.party))
        if any(s >= len(self.party) for s in self.offered_slots):
            raise ValueError(f"offered_slots {self.offered_slots} exceed party size {len(self.party)}")
        self.round = 0
        self.received_mons = []
        self.leaving = False
        self.requested_cancel = False
        self.left_gracefully = False     # the host echoed *_CANCEL to our REQUEST_CANCEL
        self._offered = set()            # slots already given away (never re-offer)
        self.trade_slot = self.offered_slots[0]

        self.rx = block.BlockReceiver()
        self.sender = None
        # Every state entered, repeats collapsed; must exist before the first `self.state =`.
        self.state_history = []
        self.state = S1_LINK

        # Persists across all trades; answers barriers only on VBlanks the engine would idle.
        self.barrier = barriermod.BarrierResponder(log=self.log)

        self.entry = EntryPhase(log=self.log)
        # Pulled before the menu exists [union_room.c:1758-1759].
        self.trainer_card = linkplayer.build_trainer_card(self.lp, wonder_card_id=0)

        self._lp_sent = False
        self._party_sent = 0
        self._party600 = monmod.build_player_party(self.party)
        self._party_blocks = monmod.party_blocks(self._party600)

        # The host's first 0xBE00 means it is in its seat; sitting before it sits into an empty room
        # (desync, black screen).
        self._host_in_seat = False
        self._host_ready = False  # host READY (0x16): its avatar is seated
        self._player_ids_seen = False
        self.host_link_player = None
        self._host_party = bytearray(monmod.PARTY_MON_SIZE * PARTY_SIZE)
        self._host_party_blocks = 0
        self.host_cursor = None
        self.received_mon = None

        self._got_ribbons = False  # giftRibbons seen: BufferTradeParties complete
        self._bt_settle = 0  # offline ribbons fallback
        self._live = False  # live: gate READY_TO_TRADE on the full BufferTradeParties
        self._selected = False
        self._reselect_wait = None      # frames until we may select again after a one-sided cancel
        self._pending_push = None
        self._anim_wait = None  # [S7]
        self._finish_sent = False  # [S7 early-arrival guard]
        self._pending_confirm = False   # CONFIRM_FINISH arrived before READY_FINISH; defer commit
        self._confirmed = False  # [S6]
        self._cancel_wait = None  # [S6]
        self._cancel_after_send = False
        self.commits = 0
        self._finish_sent_at_last_commit = False
        self.done = False
        self.cancelled = False

        # Child-initiated standby barriers [link_rfu_2.c:1566-1573]: (a)/(b) soft, (c)/(d)
        # quiescent.
        self._barrier_initiated_menu = False  # (a)
        self._barrier_initiated_seam = False  # (b)
        # Warp-quiesce standbys are session one-shots (not reset per round).
        self._barrier_initiated_warp1 = False  # post-LinkPlayer warp-quiesce (count 0)
        self._barrier_initiated_warp2 = False  # post-card warp-quiesce (count 1)
        self._warp1_emits = 0
        self._warp1_regap = 0
        self._warp2_emits = 0
        self._warp2_regap = 0
        self._warp3_emits = 0
        self._warp4_emits = 0
        self._barrier_initiated_warp3 = False
        self._barrier_initiated_warp4 = False
        self._warp3_regap = 0
        self._warp4_regap = 0
        self._self_standby_echo = 0  # highest standby count the host reflected in our slot
        # The console never broadcasts its own 0x6600 at mpId 0; the reflection is the only evidence
        # a child-initiated entry barrier landed.
        self._seat_wait_host = 0
        self._self_ready_echo = False    # the host has reflected OUR READY (0x16) back at us
        self._post_seat_logged = False
        self._self_seated = False
        self._post_seat_wait = 0
        self._save_barriers = False  # (c) [trade_scene.c:2566]
        self._save_settle = 0
        self._save_started = False
        self._save_round_wait = 0
        self._cancel_barrier_active = False  # (d)
        self._return_field_barrier_active = False  # (e)
        # After the cancel-exit standby the game returns to the overworld, re-arms held keys, and
        # only then runs the host-initiated READY_CLOSE_LINK; vanishing early breaks the teardown.
        self._post_cancel_overworld = False
        # The host's EXIT_ROOM blocks until all players are EXITING_ROOM [overworld.c:2962-2981].
        self._host_exiting = False

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        self._state = value
        if not self.state_history or self.state_history[-1] != value:
            self.state_history.append(value)

    @property
    def in_seat_phase(self):
        """True only in the overworld/seat phase (P0..P3) and after the cancel-exit standby: the
        keys callback is cleared before CB2_CreateTradeMenu [cable_club.c:918]."""
        return self._post_cancel_overworld or not self.entry.seat_phase_over

    @property
    def established(self):
        """gReceivedRemoteLinkPlayers [link_rfu_2.c:1879]. Held keys and sit must not fire before
        it: a 0xBE00 ahead of the block handshake faults the host's childSendCmdId check."""
        return self._lp_sent and self.host_link_player is not None

    @property
    def held_keys_active(self):
        """False once seated and past the post-seat rounds: the leader needs a run of idle child
        slots [host_trade.feed_child_slot], and a keepalive there deadlocks it."""
        # After its EXIT_ROOM the host waits for our 0x17 [overworld.c:2962-2981].
        if self._host_exiting:
            return True
        if not self.in_seat_phase:
            return False
        # The console never broadcasts its own 0x6600; the reflection counts too.
        if self._self_seated and max(self.barrier.host_count or 0, self._self_standby_echo) >= 3:
            return False
        # The native child idles after ~13 EMPTY following READY; the reflection of our READY marks
        # it.
        if self._self_seated and self._self_ready_echo:
            return False
        return True

    @property
    def host_in_seat(self):
        """Gate for our sit: sitting before the host reaches its seat desyncs (black screen)."""
        return self._host_in_seat

    @property
    def host_ready(self):
        """Gate for our sit: a READY while the host is still walking faults its cable-seat FSM."""
        return self._host_ready

    @property
    def host_exiting(self):
        """Answer with our EXIT_ROOM (lstate.exit()) [overworld.c:2962-2981]."""
        return self._host_exiting

    def note_self_seated(self):
        """Arms the post-seat standbys (count=2, 3) after POST_SEAT_STANDBY_DELAY."""
        if self._self_seated:
            return
        self._self_seated = True
        self._post_seat_wait = POST_SEAT_STANDBY_DELAY

    def feed_in_frame(self, unwrapped):
        completed, reqs = self.rx.feed_frame(unwrapped)
        self._scan_entry_slots(unwrapped)
        self._scan_exit_room(unwrapped)
        self._scan_own_reflection(unwrapped)
        self._observe_barriers(unwrapped)
        self._end_save_chain_on_reexchange(completed, reqs)
        for reqtype in reqs:
            self._on_req(reqtype)
        host_block = any(mpid == 0 for mpid, _c, _d in completed)
        for mpid, count, data in completed:
            if mpid == 0:
                self._on_host_block(count, data)
        # IN frames since the host last pulled or streamed a block (MockHost sends no ribbons).
        if unwrapped is not None:
            self._bt_settle = 0 if (reqs or host_block) else self._bt_settle + 1

    def _scan_entry_slots(self, unwrapped):
        if unwrapped is None or self._host_ready:
            return
        for _mpid, slot in unwrapped.get("positional", []):
            if _mpid == self.mpid:
                continue            # our OWN slot reflected back - never read host state off it
            r = rfu.parse_slot(slot)
            if not r:
                continue
            op = r["word0"] & 0xFF00
            # A SEND_PLAYER_IDS mismatch with our right-seat mpId means the hardcoded seat walk is
            # wrong.
            if op == rfu.SEND_PLAYER_IDS and not self._player_ids_seen:
                self._on_send_player_ids(slot)
            if op == rfu.SEND_HELD_KEYS and self._on_entry_held_keys(slot):
                break

    def _on_send_player_ids(self, slot):
        self._player_ids_seen = True
        count = int.from_bytes(slot[2:4], "little")
        id0 = int.from_bytes(slot[4:6], "little")
        self.info(f"Host assigned player slots: count={count} ids[0]={id0} "
                  f"(our mpId={self.mpid}).")
        if count != 2 or id0 != self.mpid:
            self.info(f"WARNING: SEND_PLAYER_IDS (count={count}, ids[0]={id0}) does not match "
                      f"the 2-player RIGHT-seat assumption (mpId {self.mpid}) - the seat walk "
                      f"is hardcoded for the right chair and may be wrong.")

    def _on_entry_held_keys(self, slot):
        """True stops the per-frame seat scan (the host just went READY)."""
        if not self._host_in_seat:
            self._host_in_seat = True
            self.entry.on_seat_reached()
            self.barrier.reset_to_idle()
            self.log("entry: host entered the trade room (first SEND_HELD_KEYS) -> emit EMPTY keepalive")
            self.info("Host entered the trade room.")
        _k = int.from_bytes(slot[2:4], "little") & 0xFF
        if _k == 0x16 and not self._host_ready:
            self._host_ready = True
            self.log("entry: host emitted READY (0x16) - host is seated; we may sit now")
            self.info("Host sat down.")
            return True
        return False

    def _scan_exit_room(self, unwrapped):
        # Host-led exit can come before any trade or after a cancel, while the seat scan is gated
        # off.
        if self._host_exiting or unwrapped is None:
            return
        for _mpid, slot in unwrapped.get("positional", []):
            r = rfu.parse_slot(slot)
            if (r and (r["word0"] & 0xFF00) == rfu.SEND_HELD_KEYS
                    and (int.from_bytes(slot[2:4], "little") & 0xFF) == 0x17):
                self._host_exiting = True
                self.log("host emitted EXIT_ROOM (0x17) - it is walking out and waiting "
                         "for ALL players to exit; respond with our EXIT_ROOM [overworld.c:2962-2981]")
                self.info("Host is leaving the room...")
                break

    def _scan_own_reflection(self, unwrapped):
        # _host_barrier_in_frame skips our reflected slot, but the reflection is the host's
        # acknowledgement and on hardware the only one.
        if unwrapped is None:
            return
        for _mpid, _slot in unwrapped.get("positional", []):
            if _mpid != self.mpid:
                continue
            _d = rfu.parse_slot(_slot)
            if (_d is not None and (_d["word0"] & 0xFF00) == rfu.SEND_HELD_KEYS
                    and (int.from_bytes(_slot[2:4], "little") & 0xFF) == 0x16
                    and not self._self_ready_echo):
                # The host consumed our READY [overworld.c:2755]; with both READY it runs
                # Task_StartWirelessTrade and waits for our count=2.
                self._self_ready_echo = True
                self.log("entry: host reflected our READY - both players seated")
            if _d is not None and _d["op"] == rfu.READY_EXIT_STANDBY:
                _c = _d.get("count")
                if _c is not None and _c > self._self_standby_echo:
                    self._self_standby_echo = _c
                    self.log(f"entry: host reflected our READY_EXIT_STANDBY count={_c}")

    def _observe_barriers(self, unwrapped):
        host_slot = self._host_barrier_in_frame(unwrapped)
        saw_barrier = host_slot is not None
        if saw_barrier:
            self.barrier.on_in_slot(host_slot)
        if unwrapped is not None:
            self.barrier.observe_frame(saw_barrier)
            if self._save_barriers:
                self._save_settle = 0 if saw_barrier else self._save_settle + 1

    def _end_save_chain_on_reexchange(self, completed, reqs):
        # Only a host block (mpId 0) or a REQ ends it; mpId-1 entries reflect our own block.
        host_reexchange = bool(reqs) or any(mpid == 0 for mpid, _c, _d in completed)
        if self._save_barriers and host_reexchange:
            self._save_barriers = False
            # Drop any in-flight save standby, else priority 5 keeps emitting the stale count.
            self.barrier.reset_to_idle()
            self.log("save-chain: host re-exchanging (REQ/block) -> ending chain, resume trade")

    def _host_barrier_in_frame(self, unwrapped):
        """This frame only (the watchdogs need per-frame truth). A standby/close slot carries no
        owner and may be coalesced past the mpId-0 offset: dispatch by op, skipping our slot."""
        if not unwrapped:
            return None
        for mpid, slot in unwrapped.get("positional", []):
            if mpid == self.mpid:
                continue
            d = rfu.parse_slot(slot)
            if d is not None and d["op"] in (rfu.READY_EXIT_STANDBY, rfu.READY_CLOSE_LINK):
                return d
        return None

    def _begin_send(self, buf):
        """Reset peer 1 first: its previous completed block would falsely ack the new one after one
        fragment."""
        self.rx.peers[1] = block.RecvBlock()
        self.sender = block.BlockSender(buf, trust_pia=self.trust_pia, stream_gap=JOINER_STREAM_GAP)
        return self.sender

    def _on_req(self, reqtype):
        """BLOCK_REQ_SIZE_100 always means the entry trainer card
        [link.c:185-190; link_rfu_2.c:1172-1173]."""
        if self.sender is not None and not self.sender.done:
            # A REQ while streaming is the host re-pulling the same block [link_rfu_2.c:1296];
            # serving it would send the next party pair early.
            return
        size = REQ_SIZE.get(reqtype, 200)
        buf = self._block_for_size(reqtype, size)
        self.log(f"REQ type={reqtype} size={size} -> send {len(buf)}B")
        self._begin_send(buf)

    def _block_for_size(self, reqtype, size):
        if reqtype == BLOCK_REQ_SIZE_100:
            self.entry.on_card_req()
            self.entry.on_card_supplied()
            return self.trainer_card
        if size == 200:
            # After the host is seated a size-200 pull is BufferTradeParties, after the keys
            # callback is cleared [cable_club.c:918]: latch P4. Before the seat it is the LinkPlayer
            # and must not.
            if self._host_in_seat:
                self.entry.on_trade_menu_open()
            # The LinkPlayerBlock is exchanged once per session [link_rfu_2.c:1813-1900]; resending
            # it on a later round shifts the party by one and drops pair #3.
            if self.round == 0 and not self._lp_sent:
                self._lp_sent = True
                return linkplayer.build_block(self.lp).ljust(200, b"\x00")
            i = self._party_sent
            self._party_sent += 1
            return self._party_blocks[i] if i < len(self._party_blocks) else b"\x00" * 200
        if size == 100:
            return self.trainer_card    # any other 100B pull = the trainer card too
        if size == 220:
            return b"\x00" * 220        # mail (none)
        if size == 40:
            return b"\x00" * 40         # giftRibbons (none)
        return b"\x00" * size

    def _on_host_block(self, count, data):
        if count == COUNT_TRAINER_CARD and not self.entry.complete:
            # The host's card is cosmetic [union_room.c:1769-1779].
            self.entry.on_host_card(data)
            return
        if count == COUNT_LINKCMD:
            cmd = int.from_bytes(data[0:2], "little")
            cursor = int.from_bytes(data[2:4], "little")
            self._on_linkcmd(cmd, cursor)
        elif count == COUNT_PARTY:
            # After the seat a host count-17 block is BufferTradeParties (latch P4); before it, its
            # LinkPlayer.
            if self._host_in_seat:
                self.entry.on_trade_menu_open()
            lp, ok = linkplayer.parse_block(data)
            # Identify the LinkPlayer by its magic: the host re-streams it first on every round.
            if ok:
                if self.host_link_player is None:
                    self.host_link_player = lp
                    self.log(f"host LinkPlayer: {lp.name} v0x{lp.version:04x}")
                    self.info("Exchanged player info with the host.")
            elif self._host_party_blocks < 3:
                i = self._host_party_blocks
                self._host_party[i * 200:(i + 1) * 200] = data[:200]
                self._host_party_blocks += 1
                self.log(f"host party block #{i + 1}/3")
                if self._host_party_blocks == 3 and self.state == S1_LINK:
                    self.state = S4_PARTY
        elif count in (COUNT_MAIL, COUNT_RIBBON):
            self.log(f"host {'mail' if count == COUNT_MAIL else 'giftRibbons'} block "
                     f"(count={count}) - consumed (cosmetic, not trade-affecting)")
            if count == COUNT_RIBBON:
                # giftRibbons is the last block of BufferTradeParties [trade.c:1444-1542];
                # READY_TO_TRADE before it leaves the host at "Communication standby".
                self._got_ribbons = True

    def _on_linkcmd(self, cmd, cursor):
        self.log(f"<- LINKCMD {LINKCMD_NAMES.get(cmd, hex(cmd))} cursor={cursor}")
        if cmd == REQUEST_CANCEL and self.leaving and self.requested_cancel and not self.done:
            # BufferTradeParties clears received flags before the menu reads commands [trade.c:1549].
            # Reanswer the leader's local Cancel if an earlier request was consumed there.
            # docs/frlg_link.md, Cancel after a trade.
            self._pending_push = linkcmd_block(REQUEST_CANCEL)
            self.info("The host selected Cancel; repeating our cancel request.")
        elif cmd == SET_MONS_TO_TRADE:
            # partnerCursorPosition = recv[0][1] + PARTY_SIZE [trade.c:1653-1657].
            self.host_cursor = cursor
            if self.state in (S5_SELECT, S4_PARTY):
                self.state = S6_CONFIRM
                self._run_confirm()
        elif cmd == START_TRADE:
            # A Leader that latched STATUS_CANCEL never STARTs [trade.c:1629-1631].
            if self.cancelled:
                return
            # anim_delay frames before READY_FINISH [trade.c:1659-1661; trade_scene.c:2527-2536].
            self.state = S7_ANIM
            self._anim_wait = self.anim_delay
        elif cmd == CONFIRM_FINISH_TRADE:
            if self.cancelled:
                return
            # CONFIRM_FINISH can land before our anim countdown ends [trade_scene.c:2547-2559];
            # defer the commit until READY_FINISH is emitted.
            if self._finish_sent:
                self._commit()
            else:
                self._pending_confirm = True
                self.log("CONFIRM_FINISH early-arrival: deferring commit until READY_FINISH sent")
        elif cmd == BOTH_CANCEL_TRADE:
            # Both sides picked CANCEL [trade.c:1715-1722]: the session ends.
            self.state = S_CANCEL
            self.cancelled = True
            self._pending_push = None
            if self.requested_cancel:
                self.left_gracefully = True
                self.log("<- BOTH_CANCEL_TRADE: graceful cancel acknowledged")
                self.info("Trade cancelled (mutual).")
            else:
                self.log("<- BOTH_CANCEL_TRADE: host cancelled the trade")
            # Only BOTH_CANCEL routes through CB_INIT_EXIT_CANCELED_TRADE -> SetLinkStandbyCallback
            # [trade.c:1643-1646,2117-2132], where the host's leader branch waits for us.
            self._cancel_barrier_active = True
            self.barrier.initiate(barriermod.STANDBY)
            self.log("barrier (d): INITIATE cancel-exit standby [trade.c:2117-2132]")
        elif cmd in (PLAYER_CANCEL_TRADE, PARTNER_CANCEL_TRADE):
            # One side selected, the other cancelled [trade.c:1695-1712, 1737-1746]: both return to
            # the trade menu [2094-2113] and the leader waits for both to select again. Ending the
            # session here left the leader waiting forever.
            # PLAYER_CANCEL while we are READY is the leader's player choosing Cancel [trade.c:1704-
            # 1712]; we cancel at the menu so their next Cancel ends the session.
            if cmd == PLAYER_CANCEL_TRADE and self.state == S5_SELECT:
                self.leaving = True
                self.log("<- PLAYER_CANCEL_TRADE at selection: the console's player cancelled; "
                         "cancelling with them")
                self.info("The console's player cancelled; Cancel again on the console to leave.")
            else:
                self.log(f"<- {LINKCMD_NAMES.get(cmd, hex(cmd))}: back to the trade menu; "
                         "selecting again")
                self.info("Trade cancelled by one side; back at the menu.")
            self.state = S4_PARTY
            self._selected = False
            self._reselect_wait = RESELECT_DELAY
            self._pending_push = None
            self._cancel_after_send = False
            self._confirmed = False
            self._cancel_wait = None
            self.cancelled = False
            self.requested_cancel = False
            self.host_cursor = None

    def _is_valid_slot(self, slot):
        """CanTradeSelectedMon stand-in [trade.c:2745-2818]: in range and non-empty.
        CANT_TRADE_LAST_MON [2809-2818] is skipped: the leader never checks it, and a one-file party
        would cancel the instant the menu opened."""
        if not (0 <= slot < len(self.party)):
            return False
        return not self.party[slot].is_empty

    def _trade_menu_live(self):
        """Live once the full BufferTradeParties has finished (ribbons seen, or settled):
        READY_TO_TRADE during it leaves the host at "Communication standby"."""
        base = (self._host_party_blocks >= 3 and self._lp_sent
                and self._party_sent >= len(self._party_blocks))
        if not self._live:
            return base                  # offline MockHost sends SET_MONS right after the party
        return base and (self._got_ribbons or self._bt_settle >= BUFFERTRADE_SETTLE)

    def _partner_mon_invalid(self):
        """PARTNER_MON_INVALID stand-in [trade.c:1965-1968]; opt-in, legitimacy is not decodable
        offline."""
        if not self.refuse_partner_deoxys_mew or self.host_cursor is None:
            return False
        idx = self.host_cursor % PARTY_SIZE
        off = idx * monmod.PARTY_MON_SIZE
        offered = monmod.Mon(bytes(self._host_party[off:off + monmod.PARTY_MON_SIZE]))
        return offered.species in (SPECIES_MEW, SPECIES_DEOXYS)

    def _confirm_verdict(self):
        """CheckValidityOfTradeMons stand-in [trade.c:1951-1973]; the partner is checked first."""
        if self._partner_mon_invalid():
            return PARTNER_MON_INVALID
        if not self._is_valid_slot(self.trade_slot):
            return PLAYER_MON_INVALID
        return BOTH_MONS_VALID

    def _run_confirm(self):
        """Confirm prompt [trade.c:2073-2029]: decline -> READY_CANCEL now [2019-2023]; valid ->
        INIT_BLOCK [1991-1996]; invalid mon -> READY_CANCEL after 180f [1986-1990/1997-2001]."""
        if self._confirmed:
            return
        self._confirmed = True
        if self.decline:
            self.log("confirm: NO (declining) -> READY_CANCEL_TRADE (immediate) [trade.c:2019-2023]")
            self.info("Declining the trade; cancelling to leave.")
            self._pending_push = linkcmd_block(READY_CANCEL_TRADE)
            self.cancelled = True
            return
        verdict = self._confirm_verdict()
        if verdict == BOTH_MONS_VALID:
            self.log("confirm: BOTH_MONS_VALID -> INIT_BLOCK (immediate) [trade.c:1991-1996]")
            self._pending_push = linkcmd_block(INIT_BLOCK)
        elif verdict == PLAYER_MON_INVALID:
            self.log("confirm: PLAYER_MON_INVALID -> READY_CANCEL_TRADE in 180f [trade.c:1986-1990]")
            self.info("Cannot keep our last living Pokémon; cancelling to leave.")
            self._cancel_wait = INVALID_CANCEL_DELAY
            self.cancelled = True
        else:  # PARTNER_MON_INVALID
            self.log("confirm: PARTNER_MON_INVALID -> READY_CANCEL_TRADE in 180f [trade.c:1997-2001]")
            self.info("Host offered an illegitimate Pokémon; cancelling to leave.")
            self._cancel_wait = INVALID_CANCEL_DELAY
            self.cancelled = True

    def _commit(self):
        """TradeMons [trade_scene.c:1054-1083]: host party[host_cursor % PARTY_SIZE] into our
        offered slot. More trades re-arm (BufferTradeParties re-runs [trade.c:935]), else leave."""
        # Capture READY_FINISH-before-commit before _reset_round_state clears it.
        self._finish_sent_at_last_commit = self._finish_sent
        self.commits += 1
        received = None
        offered_slot = self.offered_slots[self.round]
        if self.host_cursor is not None:
            idx = self.host_cursor % PARTY_SIZE
            off = idx * monmod.PARTY_MON_SIZE
            received = monmod.Mon(bytes(self._host_party[off:off + 100]))
            self.received_mon = received
            self.received_mons.append(received)
            self.info("Trade confirmed.")
            self.log(f"RECEIVED (trade {self.round + 1}/{self.trades}): {received.describe()}")
            self.party[offered_slot] = received
        self._offered.add(offered_slot)
        self.round += 1
        self.state = S8_DONE

        # Post-trade save chain [trade_scene.c:2566-2725]; ends when the host re-exchanges.
        self._save_barriers = True
        self._save_settle = 0
        self._save_started = False
        self._save_round_wait = 0

        if self.round < self.trades:
            self._arm_next_round()
        else:
            self.leaving = True
            self.log(f"all {self.trades} trade(s) committed -> entering cancel-to-leave")
            self.info(f"All {self.trades} trade(s) complete; cancelling to leave.")
            self._arm_leave_round()

    def _reset_round_state(self):
        """Keeps _lp_sent: gReceivedRemoteLinkPlayers never clears on the trade path
        [link_rfu_2.c:1879], and resending the LinkPlayerBlock as party block #1 drops pair #3."""
        self._party_sent = 0
        self._party600 = monmod.build_player_party(self.party)
        self._party_blocks = monmod.party_blocks(self._party600)
        self._host_party = bytearray(monmod.PARTY_MON_SIZE * PARTY_SIZE)
        self._host_party_blocks = 0
        self.host_cursor = None
        self._selected = False
        # BufferTradeParties re-runs on menu re-entry [trade.c:935]; a stale _got_ribbons fires
        # READY_TO_TRADE before the host's Leader_ReadLinkBuffer runs: deadlock.
        self._got_ribbons = False
        self._bt_settle = 0
        self._anim_wait = None
        self._finish_sent = False
        self._pending_confirm = False
        self._confirmed = False
        self._cancel_wait = None
        self._reselect_wait = None
        self._barrier_initiated_menu = False
        self._barrier_initiated_seam = False

    def _arm_next_round(self):
        self._reset_round_state()
        self.trade_slot = self.offered_slots[self.round]
        self.state = S1_LINK
        self.log(f"-> next trade {self.round + 1}/{self.trades}, offering slot {self.trade_slot}")

    def _arm_leave_round(self):
        """With leaving set, the selection guard emits REQUEST_CANCEL instead of READY_TO_TRADE."""
        self._reset_round_state()
        self.state = S1_LINK

    def _sustain_standby(self, count, emits_attr, regap_attr, gap=SAVE_BARRIER_GAP):
        """Bounded burst of `count`, re-armed every `gap` idle frames."""
        emits = getattr(self, emits_attr)
        if emits < WARP_STANDBY_EMITS:
            setattr(self, emits_attr, emits + 1)
            setattr(self, regap_attr, 0)
            return rfu.exit_standby_words(count)
        regap = getattr(self, regap_attr) + 1
        setattr(self, regap_attr, regap)
        if regap >= gap:
            setattr(self, emits_attr, 0)
            setattr(self, regap_attr, 0)
        return [0] * 7

    def _run_save_chain(self):
        """Save chain [trade_scene.c:2566-2725]: the host's save writes pause it 0.3-1.8 s between
        rounds, so it ends only on host re-exchange, never on a quiet window. True while it runs."""
        if not self.barrier.active:
            if self._save_settle > SAVE_CHAIN_TIMEOUT:
                self._save_barriers = False
                self.log(f"save-chain: host vanished for >{SAVE_CHAIN_TIMEOUT}f -> chain done (safety net)")
                return False
            # No inter-round pacing: the host is paced by its save writes.
            self._save_started = True
            self.barrier.initiate(barriermod.STANDBY)
        return True

    def _advance_timers(self):
        """Ticks every VBlank, from tick() or, when the send window is gated, from
        poll_send_done(), never both. Gated behind the window, READY_FINISH never went out."""
        if self._reselect_wait is not None:
            if self._reselect_wait > 0:
                self._reselect_wait -= 1
            else:
                self._reselect_wait = None
        if self._cancel_wait is not None:
            if self._cancel_wait > 0:
                self._cancel_wait -= 1
            else:
                self._cancel_wait = None
                self._pending_push = linkcmd_block(READY_CANCEL_TRADE)
                self.log("-> READY_CANCEL_TRADE (after 180f)")
        if self._anim_wait is not None:
            if self._anim_wait > 0:
                self._anim_wait -= 1
            else:
                self._anim_wait = None
                self._pending_push = linkcmd_block(READY_FINISH_TRADE)
                self._finish_sent = True
                self.info("Confirming trade...")
                self.log("-> READY_FINISH_TRADE")
                if self._pending_confirm:
                    self._pending_confirm = False
                    self._commit()

    def poll_send_done(self):
        """Window-gated pump: timers and an in-flight HOLD -> DONE (SendLastBlock runs every
        VBlank; gating it deadlocked the party exchange). A HOLD tick never moves STREAM."""
        self._advance_timers()
        if self.sender is not None and self.sender.state == block.HOLD:
            self.tick(sender_only=True)

    def tick(self, sender_only=False):
        """sender_only: advance only the block sender, so a HOLD tick never runs the entry
        barrier in a call whose words poll_send_done discards."""
        words = self._tick_sender(sender_only)
        if words is not None:
            return words

        words = self._tick_exit_barriers()
        if words is not None:
            return words

        words = self._tick_save_chain()
        if words is not None:
            return words

        words = self._tick_menu_and_push()
        if words is not None:
            return words

        words = self._tick_warp_standbys()
        if words is not None:
            return words

        words = self._tick_seat_standbys()
        if words is not None:
            return words

        # Barrier only on a slot the engine would have idled; a barrier and a block never coexist
        # [link_rfu_2.c:1553/1569/1586].
        bwords = self.barrier.want_emit()
        if bwords is not None:
            return bwords

        return [0] * 7

    def _tick_sender(self, sender_only):
        ack = self.rx.peers[1]          # the host's reflection of our block = wire ACK
        if self.sender is None:
            return None
        # Never stream ours into the host's own block (peer 0) mid-transfer.
        host_rx = self.rx.peers[0]
        peer_sending = bool(host_rx.receiving and not host_rx.done)
        words = self.sender.tick(ack, peer_sending=peer_sending)
        if self.sender.done:
            self.sender = None
            if self._cancel_after_send and not self.done:
                self._cancel_after_send = False
                self.state = S_CANCEL
                # Only BOTH_CANCEL_TRADE ends the session; a PARTNER/PLAYER_CANCEL returns both to
                # the menu [trade.c:1695-1712, 1737-1746], where we select CANCEL again.
                self.leaving = True
                self.log("cancel sent -> awaiting the leader's *_CANCEL echo")
        # HOLD has no live watchdog (an early DONE deadlocked the party exchange); its idle frames
        # yield or the entry warp barriers starve.
        if sender_only or (words[0] & 0xFFFF) != 0 or self.sender is None \
                or self.sender.state != block.HOLD:
            return words
        return None

    def _tick_exit_barriers(self):
        # Barrier (d), cancel-exit standby [trade.c:2117-2132].
        if self._cancel_barrier_active:
            if self.barrier.active:
                return self.barrier.want_emit() or [0] * 7  # never None while quiescent
            self._cancel_barrier_active = False
            # Then a second SetLinkStandbyCallback [field_fadetransition.c,
            # Task_ReturnToFieldRecordMixing]; the host black-screens until we complete it.
            self._return_field_barrier_active = True
            self.barrier.initiate(barriermod.STANDBY)
            self.log("barrier (e): INITIATE return-to-field sync standby [field_fadetransition.c "
                     "Task_ReturnToFieldRecordMixing case 0 -> SetLinkStandbyCallback; host black-screens "
                     "at case 1 until we complete it]")

        # Barrier (e), return-to-field standby.
        if self._return_field_barrier_active:
            if self.barrier.active:
                return self.barrier.want_emit() or [0] * 7  # never None while quiescent
            self._return_field_barrier_active = False
            self.done = True
            # Stay after done: the host's READY_CLOSE_LINK round still needs answering.
            self._post_cancel_overworld = True
            self.log("barrier (e): return-to-field standby passed -> done (post-cancel overworld; held-keys "
                     "re-armed, awaiting host READY_CLOSE_LINK)")

        # Post-cancel overworld: answer the host's barriers; IDLE hands over to held keys.
        if self._post_cancel_overworld and self.barrier.active:
            return self.barrier.want_emit() or [0] * 7  # never None while quiescent
        return None

    def _tick_save_chain(self):
        # Barrier (c), save chain.
        if self._save_barriers:
            if self._run_save_chain():
                # want_emit() is None between rounds
                return self.barrier.want_emit() or [0] * 7
        return None

    def _tick_menu_and_push(self):
        self._advance_timers()

        # Barrier (b), menu->scene seam [trade.c:2159-2166]: soft, so a silent host does not stall
        # the anim.
        if self._anim_wait is not None and not self._barrier_initiated_seam:
            self._barrier_initiated_seam = True
            self.barrier.initiate(barriermod.STANDBY)
            self.log("barrier (b): INITIATE menu->scene-seam standby [trade.c:2159-2166]")

        # Barrier (a) is never initiated: no standby sits between the party exchange and
        # START_TRADE; initiating it runs one round ahead of the host and floods its buffer.

        self._select_offer()

        if self._pending_push is None:
            return None
        buf = self._pending_push
        self._pending_push = None
        # Cancel opcodes leave only after the host receives the block [trade.c:2094-2132].
        pushed_cmd = int.from_bytes(buf[0:2], "little")
        if pushed_cmd in (REQUEST_CANCEL, READY_CANCEL_TRADE):
            self._cancel_after_send = True
            self.cancelled = True
        return self._begin_send(buf).tick(self.rx.peers[1])

    def _select_offer(self):
        # S5: SetReadyToTrade [trade.c:1905-1908], or CANCEL -> REQUEST_CANCEL [trade.c:2049].
        if (not self._selected and self.state in (S4_PARTY,) and self._reselect_wait is None
                and self._trade_menu_live() and self._pending_push is None):
            self._selected = True
            self.entry.on_trade_menu_live()
            if self.leaving:
                self.info("Cancelling the trade menu...")
                self.log("-> REQUEST_CANCEL (leaving: CANCEL selected) [trade.c:2049]")
                self._pending_push = linkcmd_block(REQUEST_CANCEL)
                self.requested_cancel = True
                self.cancelled = True
            elif self._is_valid_slot(self.trade_slot):
                self.state = S5_SELECT
                self._pending_push = linkcmd_block(READY_TO_TRADE, self.trade_slot)
                self.info("Offered our Pokémon; waiting on the host.")
                self.log(f"-> READY_TO_TRADE cursor={self.trade_slot} "
                         f"(trade {self.round + 1}/{self.trades})")
            else:
                self.log(f"slot {self.trade_slot} fails CanTradeSelectedMon -> REQUEST_CANCEL")
                self.info(f"Cannot trade slot {self.trade_slot}; cancelling to leave.")
                self.leaving = True
                self._pending_push = linkcmd_block(REQUEST_CANCEL)
                self.requested_cancel = True
                self.cancelled = True

    def _tick_warp_standbys(self):
        # Before the seat the host waits for our READY_EXIT_STANDBY (count=0 post-LinkPlayer,
        # count=1 post-card).
        if self.established and not self._host_in_seat:
            wcount = 0 if not self.entry.card_supplied else 1
            # One burst, then silence: the leader queues an echo per count, which preempts its
            # held-key route, so it never walks. The console never emits the standby in its own mp0
            # row.
            if wcount == 0:
                if not self._barrier_initiated_warp1:
                    self._barrier_initiated_warp1 = True
                    self.log("warp#1: post-LinkPlayer READY_EXIT_STANDBY count=0 (one-shot burst)")
                if self._warp1_emits < WARP_STANDBY_EMITS:
                    self._warp1_emits += 1
                    return rfu.exit_standby_words(0)
            else:
                if not self._barrier_initiated_warp2:
                    self._barrier_initiated_warp2 = True
                    self.log("warp#2: post-card READY_EXIT_STANDBY count=1 (one-shot burst)")
                if self._warp2_emits < WARP_STANDBY_EMITS:
                    self._warp2_emits += 1
                    return rfu.exit_standby_words(1)
            return [0] * 7  # quiet so the leader can walk
        return None

    def _tick_seat_standbys(self):
        # Post-seat standbys count=2 then 3, before the host pulls the party.
        if self.established and self._self_seated and not self.entry.seat_phase_over:
            words = self._seat_wait_for_host()
            if words is not None:
                return words
            # The host's reflection of our READY proves it reached the wire; skip the delay.
            if self._post_seat_wait > 0 and not self._self_ready_echo:
                self._post_seat_wait -= 1
                return [0] * 7
            # The host waits silently for each mutual barrier [link_rfu_2.c:1577-1591]: sustain each
            # count. Once it broadcasts its own count at mp0 trust only that; a reflection proves it
            # saw our slot, not that it completed.
            hc_own = self.barrier.host_count or 0
            hc = hc_own if hc_own >= 2 else max(hc_own, self._self_standby_echo)
            if hc < 2:
                if not self._barrier_initiated_warp3:
                    self._barrier_initiated_warp3 = True
                    self.log("warp#3: post-seat READY_EXIT_STANDBY count=2 (sustained until host completes)")
                return self._sustain_standby(2, "_warp3_emits", "_warp3_regap", gap=ENTRY_BARRIER_GAP)
            if hc < 3:  # count=3 only after the host did count=2
                if not self._barrier_initiated_warp4:
                    self._barrier_initiated_warp4 = True
                    self.log("warp#4: post-seat READY_EXIT_STANDBY count=3 (host reached count=2; "
                             "sustained until host completes)")
                return self._sustain_standby(3, "_warp4_emits", "_warp4_regap", gap=POST_SEAT_REARM_GAP)
            return [0] * 7
        return None

    def _seat_wait_for_host(self):
        """Idles until the host's own READY (0x16), then falls through by returning None."""
        # CABLE_SEAT_SUCCESS needs all players READY [overworld.c:2988-2999]; count=2 at a waiting
        # host faults it. Only the host's 0x16 counts: DPAD codes are nulled under queue pressure
        # [overworld.c:2786-2810].
        _host_settled = self._host_ready
        if not _host_settled:
            self._seat_wait_host += 1
            if self._seat_wait_host <= SEAT_HOST_READY_MAX:
                if self._seat_wait_host == 1:
                    self.info("Seated; waiting for the host to reach its chair.")
                return [0] * 7
            if self._seat_wait_host == SEAT_HOST_READY_MAX + 1:
                self.info("Host never settled at its chair; starting the post-seat rounds anyway.")
        elif not self._post_seat_logged:
            self._post_seat_logged = True
            self.info("Both players seated; starting the post-seat standby rounds.")
        return None
