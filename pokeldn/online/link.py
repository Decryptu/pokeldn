"""Finding a partner by game and code, and the trade channel to it (docs/online.md).

Everyone running the same game with the same code publishes to one room on the relays. Each app
announces itself every few seconds; the lower signing key invites a higher one that is free, and an
accepted invite pairs the two. From then on they exchange numbered, acknowledged messages encrypted
with an X25519 key only the pair holds. A launcher drives `Partner` from its own loop: every method
returns at once and every answer is a property it polls.
"""
import base64
import hashlib
import json
import os
import threading
import time

from Crypto.Cipher import AES
from Crypto.Protocol import DH
from Crypto.PublicKey import ECC

from pokeldn.online import relays

PROTOCOL = 1
KIND = 21059                 # ephemeral (NIP-01: 20000-29999): relays pass it on and keep nothing
ANNOUNCE_PERIOD = 2.5
PEER_STALE = 8.0             # a peer silent this long is no longer offered an invite
INVITE_TIMEOUT = 6.0
SKIP_AFTER_REFUSAL = 10.0
RESEND_PERIOD = 2.0
PING_PERIOD = 4.0
HELLO_TIMEOUT = 12.0         # paired, but nothing heard back: search again
LOST_AFTER = 45.0
TICK = 0.1
ACK_DELAY = 0.3              # one ack covers what arrives together; relays rate-limit bursts


def room_id(game: str, code: str) -> str:
    """Everyone with this game and code shares the room; an empty code is the open room."""
    text = f"pokeldn online {PROTOCOL}|{game}|{code or 'open'}"
    return hashlib.sha256(text.encode()).hexdigest()


def _seal(key: bytes, payload: dict) -> str:
    nonce = os.urandom(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    body, tag = cipher.encrypt_and_digest(json.dumps(payload, separators=(",", ":")).encode())
    return base64.b64encode(nonce + body + tag).decode()


def _open(key: bytes, content: str) -> dict | None:
    try:
        raw = base64.b64decode(content, validate=True)
        cipher = AES.new(key, AES.MODE_GCM, nonce=raw[:12])
        payload = json.loads(cipher.decrypt_and_verify(raw[12:-16], raw[-16:]))
    except (ValueError, KeyError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


class Round:
    """What the partner said about one trade."""

    def __init__(self):
        self.offer: bytes | None = None
        self.accepted = False
        self.withdrawn = 0
        self.done = False
        self.refused = ""            # why the partner's app refused our offer
        self.shared: dict[str, bytes] = {}   # what else their console sent, by name


class Partner:
    """One online partner for a launcher. States: connecting, searching, paired, lost, closed."""

    def __init__(self, game, code="", name="", app="", log=print, validate=None, pool_factory=None,
                 clock=time.time):
        self.game, self.code, self.name, self.app = game, code or "", name, app
        self.log, self.validate, self.clock = log, validate, clock
        self.room = room_id(game, self.code)
        self.room_key = hashlib.sha256(b"pokeldn room key|" + bytes.fromhex(self.room)).digest()
        self.me = relays.Identity()
        self.dh = ECC.generate(curve="curve25519")
        self.dh_public = self.dh.public_key().export_key(format="raw").hex()
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.state = "connecting"
        self.peers: dict[str, dict] = {}       # signing key -> {x, name, app, seen, first, busy}
        self.skip: dict[str, float] = {}
        self.invite = None                    # (peer, deadline)
        self.peer = self.peer_name = None
        self.key = None
        self.paired_at = 0.0
        self.heard = 0.0
        self.out_seq = 0
        self.unacked: dict[int, dict] = {}    # seq -> message
        self.last_sent = 0.0
        self.in_next = 1
        self.early: dict[int, dict] = {}
        self.ack_due = 0.0
        self.last_announce = 0.0
        self.round = 1
        self.rounds: dict[int, Round] = {}
        self.ended = ""                       # why the partner left
        self.traded = False                   # an offer went either way: a lost partner stays lost
        self.mine = {"offer": None, "accepted": False, "shared": {}}   # the local console, this round
        factory = pool_factory or (lambda on_event: relays.RelayPool(relays.relay_urls(), on_event,
                                                                     log=log))
        self.pool = factory(self._on_event)
        self.thread = threading.Thread(target=self._run, name="online partner", daemon=True)

    # The launcher's side

    def start(self, thread=True):
        """thread=False leaves the ticking to the caller's tick(), for a test on a fake clock."""
        self.pool.subscribe("pokeldn", {"kinds": [KIND], "#t": [self.room],
                                        "since": int(self.clock()) - 10})
        self.pool.start()
        if thread:
            self.thread.start()
        where = f"code {self.code}" if self.code else "no code"
        self.log(f"[online] looking for a partner: {self.game}, {where}")

    def close(self, reason="closed"):
        with self.lock:
            if self.state == "paired":
                self._send({"t": "bye", "why": reason}, reliable=False)
            self.state = "closed"
        self.closed.set()
        self.pool.close()

    @property
    def paired(self) -> bool:
        return self.state == "paired"

    def theirs(self) -> Round:
        with self.lock:
            return self.rounds.setdefault(self.round, Round())

    # What the local console did this round is kept, so a partner found later hears it.

    def offer(self, record: bytes):
        """The local console offers `record` in this round."""
        with self.lock:
            self.mine = {"offer": bytes(record), "accepted": False, "shared": self.mine["shared"]}
            self._send(self._offer_message())

    def withdraw(self):
        with self.lock:
            self.mine = {"offer": None, "accepted": False, "shared": self.mine["shared"]}
            self._send({"t": "withdraw", "r": self.round})

    def share(self, key: str, data: bytes):
        """Something else the local console sent this round that the partner's launcher replays,
        such as a FireRed party block."""
        with self.lock:
            self.mine["shared"][key] = bytes(data)
            self._send(self._share_message(key))

    def _share_message(self, key):
        return {"t": "share", "r": self.round, "k": key,
                "d": base64.b64encode(self.mine["shared"][key]).decode()}

    def accept(self):
        with self.lock:
            self.mine["accepted"] = True
            self._send({"t": "accept", "r": self.round})

    def unaccept(self):
        with self.lock:
            self.mine["accepted"] = False
            self._send({"t": "unaccept", "r": self.round})

    def _offer_message(self):
        self.traded = self.traded or self.state == "paired"
        return {"t": "offer", "r": self.round, "d": base64.b64encode(self.mine["offer"]).decode()}

    def refuse(self, reason):
        self._send({"t": "refused", "r": self.round, "why": reason})

    def done(self):
        """This round's trade completed on the local console; the next round starts."""
        with self.lock:
            self._send({"t": "done", "r": self.round})
            self.round += 1
            self.mine = {"offer": None, "accepted": False, "shared": {}}

    # Relay events, on a relay thread

    def _on_event(self, event):
        if event.get("pubkey") == self.me.public or event.get("kind") != KIND:
            return
        tags = event.get("tags") or []
        if ["t", self.room] not in tags:
            return
        outer = _open(self.room_key, event.get("content", ""))
        if outer is None:
            return
        sender = event["pubkey"]
        to = next((t[1] for t in tags if len(t) >= 2 and t[0] == "p"), None)
        with self.lock:
            if outer.get("t") == "here":
                self._on_announce(sender, outer)
            elif to == self.me.public and isinstance(outer.get("x"), str) and isinstance(outer.get("c"), str):
                key = self._pair_key(sender, outer["x"])
                inner = _open(key, outer["c"]) if key else None
                if inner is not None:
                    self._on_direct(sender, outer["x"], key, inner)

    def _on_announce(self, sender, body):
        if body.get("v") != PROTOCOL or not isinstance(body.get("x"), str):
            return
        now = self.clock()
        known = self.peers.get(sender)
        self.peers[sender] = {"x": body["x"], "name": str(body.get("n", ""))[:24],
                              "app": str(body.get("a", ""))[:24], "seen": now,
                              "first": known["first"] if known else now, "busy": bool(body.get("busy"))}

    def _pair_key(self, peer, x_hex):
        try:
            shared = DH.key_agreement(static_priv=self.dh,
                                      static_pub=DH.import_x25519_public_key(bytes.fromhex(x_hex)),
                                      kdf=lambda z: z)
        except ValueError:
            return None
        ends = "|".join(sorted((f"{self.me.public}:{self.dh_public}", f"{peer}:{x_hex}")))
        return hashlib.sha256(b"pokeldn pair|" + self.room.encode() + b"|" + ends.encode() + shared).digest()

    def _direct(self, peer, x_hex, key, inner):
        content = _seal(self.room_key, {"x": self.dh_public, "c": _seal(key, inner)})
        event = self.me.event(KIND, [["t", self.room], ["p", peer]], content)
        self.pool.publish(event)

    def _on_direct(self, sender, x_hex, key, msg):
        kind = msg.get("t")
        now = self.clock()
        if kind == "invite":
            if self.state == "searching" and self.invite is None and sender < self.me.public:
                self._direct(sender, x_hex, key, {"t": "yes", "n": self.name})
                self._pair(sender, x_hex, key, str(msg.get("n", ""))[:24])
            else:
                self._direct(sender, x_hex, key, {"t": "no"})
            return
        if kind in ("yes", "no"):
            if self.invite and self.invite[0] == sender and self.state == "searching":
                if kind == "yes":
                    self._pair(sender, x_hex, key, str(msg.get("n", ""))[:24])
                else:
                    self.skip[sender] = now + SKIP_AFTER_REFUSAL
                    self.invite = None
            elif kind == "yes" and not (self.state == "paired" and sender == self.peer):
                self._direct(sender, x_hex, key, {"t": "bye", "why": "taken"})
            return
        if (self.state == "searching" and self.invite and self.invite[0] == sender
                and isinstance(msg.get("s"), int)):
            # Relays do not keep order: the partner's first message can overtake its yes.
            self._pair(sender, x_hex, key, self.peers.get(sender, {}).get("name", ""))
        if self.state != "paired" or sender != self.peer:
            if kind not in ("bye", "ping"):
                self._direct(sender, x_hex, key, {"t": "bye", "why": "not paired"})
            return
        self.heard = now
        ack = msg.get("a")
        if isinstance(ack, int):
            for seq in [s for s in self.unacked if s <= ack]:
                del self.unacked[seq]
        seq = msg.get("s")
        if kind == "bye":
            self._lose(f"the partner left ({msg.get('why', '')})".replace(" ()", ""))
            return
        if not isinstance(seq, int):
            return
        if seq >= self.in_next:
            self.early[seq] = msg
        while self.in_next in self.early:
            self._deliver(self.early.pop(self.in_next))
            self.in_next += 1
        self.ack_due = self.ack_due or now + ACK_DELAY

    def _deliver(self, msg):
        kind, number = msg.get("t"), msg.get("r")
        if kind == "hello":
            self.log(f"[online] connected to {self.peer_name or 'a partner'}")
            return
        if not isinstance(number, int) or number < 1:
            return
        theirs = self.rounds.setdefault(number, Round())
        if kind == "offer":
            try:
                record = base64.b64decode(msg.get("d", ""), validate=True)
            except ValueError:
                return
            reason, what = self.validate(record) if self.validate else (None, "a Pokemon")
            if reason:
                self.log(f"[online] refused the partner's Pokemon: {reason}")
                self._send({"t": "refused", "r": number, "why": reason})
                return
            theirs.offer, theirs.accepted, theirs.refused = record, False, ""
            self.traded = True
            self.log(f"[online] {self.peer_name} offers {what}")
        elif kind == "share" and isinstance(msg.get("k"), str):
            try:
                theirs.shared[msg["k"][:32]] = base64.b64decode(msg.get("d", ""), validate=True)
            except ValueError:
                return
        elif kind == "withdraw":
            theirs.offer, theirs.accepted = None, False
            theirs.withdrawn += 1
            self.log(f"[online] {self.peer_name} took back their offer")
        elif kind == "accept":
            theirs.accepted = True
            self.log(f"[online] {self.peer_name} confirmed")
        elif kind == "unaccept":
            theirs.accepted = False
            self.log(f"[online] {self.peer_name} took back their confirmation")
        elif kind == "refused":
            theirs.refused = str(msg.get("why", ""))[:200]
            self.log(f"[online] {self.peer_name}'s app refused your Pokemon: {theirs.refused}")
        elif kind == "done":
            theirs.done = True
            self.log(f"[online] {self.peer_name}'s trade {number} is complete")

    def _pair(self, peer, x_hex, key, name):
        self.state = "paired"
        self.peer, self.peer_name, self.key, self.peer_x = peer, name or "a partner", key, x_hex
        self.invite = None
        self.paired_at = self.heard = self.clock()
        self.log(f"[online] paired with {self.peer_name}")
        self._announce(force=True)
        self._send({"t": "hello", "n": self.name, "a": self.app})
        for key in self.mine["shared"]:
            self._send(self._share_message(key))
        if self.mine["offer"] is not None:
            self._send(self._offer_message())
            if self.mine["accepted"]:
                self._send({"t": "accept", "r": self.round})

    def _lose(self, why):
        if self.state != "paired":
            return
        if not self.traded:
            # Nothing was offered on either side yet: look for someone else.
            self.log(f"[online] {why}; searching again")
            self._reset_search()
            return
        self.state = "lost"
        self.ended = why
        self.log(f"[online] {why}")

    # Sending

    def _send(self, msg, reliable=True):
        with self.lock:
            if self.state != "paired":
                return
            body = dict(msg, a=self.in_next - 1)
            if reliable:
                self.out_seq += 1
                body["s"] = self.out_seq
                self.unacked[self.out_seq] = body
            self._direct(self.peer, self.peer_x, self.key, body)
            self.last_sent = self.clock()
            self.ack_due = 0.0

    def _announce(self, force=False):
        now = self.clock()
        if not force and now - self.last_announce < ANNOUNCE_PERIOD:
            return
        self.last_announce = now
        body = {"t": "here", "v": PROTOCOL, "x": self.dh_public, "n": self.name, "a": self.app,
                "busy": self.state != "searching"}
        self.pool.publish(self.me.event(KIND, [["t", self.room]], _seal(self.room_key, body)))

    # The ticker

    def _run(self):
        while not self.closed.wait(TICK):
            self.tick()

    def tick(self):
        try:
            with self.lock:
                self._tick()
        except Exception as exc:
            self.log(f"[online] {type(exc).__name__}: {exc}")

    def _tick(self):
        now = self.clock()
        if self.state == "connecting":
            if self.pool.connected():
                self.state = "searching"
                self.log("[online] waiting for a partner")
            return
        if self.state == "searching":
            self._announce()
            if self.invite and now > self.invite[1]:
                self.skip[self.invite[0]] = now + SKIP_AFTER_REFUSAL
                self.invite = None
            if self.invite is None:
                free = [(info["first"], peer) for peer, info in self.peers.items()
                        if peer > self.me.public and not info["busy"]
                        and now - info["seen"] < PEER_STALE and self.skip.get(peer, 0) < now]
                if free:
                    peer = min(free)[1]
                    x_hex = self.peers[peer]["x"]
                    key = self._pair_key(peer, x_hex)
                    if key:
                        self.invite = (peer, now + INVITE_TIMEOUT)
                        self._direct(peer, x_hex, key, {"t": "invite", "n": self.name})
            return
        if self.state != "paired":
            return
        self._announce()
        if self.in_next == 1 and now - self.paired_at > HELLO_TIMEOUT:
            # The invite's answer was lost on the other side; nothing came back.
            self.log("[online] the partner did not answer; searching again")
            self._reset_search()
            return
        if now - self.heard > LOST_AFTER:
            self._lose("lost the partner")
            return
        if self.unacked and now - self.last_sent > RESEND_PERIOD:
            for body in list(self.unacked.values()):
                self._direct(self.peer, self.peer_x, self.key, dict(body, a=self.in_next - 1))
            self.last_sent = now
        elif now - self.last_sent > PING_PERIOD or (self.ack_due and now >= self.ack_due):
            self._send({"t": "ping"}, reliable=False)

    def _reset_search(self):
        self.skip[self.peer] = self.clock() + SKIP_AFTER_REFUSAL
        self.state = "searching"
        self.rounds, self.round = {}, 1
        self.peer = self.peer_name = self.key = None
        self.out_seq, self.unacked, self.in_next, self.early, self.ack_due = 0, {}, 1, {}, 0.0
        self._announce(force=True)
