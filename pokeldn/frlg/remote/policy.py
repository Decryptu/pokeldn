"""Main-thread adapter between the probe coordinator and HostTradeEngine."""

import base64
import hashlib

from pokeldn.frlg.remote.coordinator import ProbeCoordinator
from pokeldn.frlg.link import linkplayer
from pokeldn.frlg.remote.journal import JournalError
from pokeldn.frlg.remote.protocol import PHASE_SIZES, ProtocolError, logical_bytes
from pokeldn.frlg.remote.transport import TransportError, TransportEvent


class RemoteTradePolicy:
    """Exchange exact game business blocks and stop at the trade menu."""

    def __init__(self, transport, *, log=lambda *_args: None, journal=None,
                 phase_gate=None):
        self.transport = transport
        self.log = log
        self.journal = journal
        self.coordinator = ProbeCoordinator(transport.run_id)
        self.engine = None
        self.failed = None
        self.journal_failure = None
        self.local_game_identity = None
        self.phase_gate = phase_gate
        self._phase_gate_held_logged = False
        self._phase_gate_released_logged = False

    def attach_engine(self, engine):
        if self.engine is not None:
            raise RuntimeError("remote policy already has an engine")
        self.engine = engine

    def _record(self, event, **fields):
        if self.journal is not None:
            try:
                self.journal.append(event, **fields)
            except JournalError as exc:
                self.journal_failure = str(exc)
                self.log(f"P0 journal error: {self.journal_failure}")

    def _mark_failed(self, reason):
        if self.failed is not None:
            return
        self.failed = str(reason)
        self.coordinator.remote_link_state = "failed"
        self.log(f"LAN probe control failed: {self.failed}. Local RFU traffic remains active.")
        self._record("lan_control_failed", code="link_lost")

    def publish_local_block(self, phase, data):
        raw = bytes(data)
        try:
            logical = logical_bytes(phase, raw)
            added = self.coordinator.record_local_block(phase, raw)
        except (ProtocolError, ValueError) as exc:
            self._mark_failed(exc)
            return
        digest = hashlib.sha256(logical).hexdigest()
        if added and self.failed is None:
            try:
                self.transport.send("PEER_BLOCK", {
                    "data": base64.b64encode(raw).decode("ascii"), "digest": digest,
                }, phase=phase)
            except TransportError as exc:
                self._mark_failed(exc)
        self.log(f"LAN probe sent local {phase} block ({PHASE_SIZES[phase]} bytes, sha256={digest}).")
        self._record("local_block_received", phase=phase, length=len(logical), digest=digest)

    def take_remote_block(self, phase):
        if phase not in self.coordinator.remote_blocks:
            return None
        if self.phase_gate is not None:
            gate_state = self.phase_gate.poll(phase)
            if gate_state == "held":
                if not self._phase_gate_held_logged:
                    self._phase_gate_held_logged = True
                    self.log(f"P0 test gate holding peer {phase}; create "
                             f"{self.phase_gate.release_file} to release it.")
                    self._record("test_gate_held", phase=phase)
                return None
            if gate_state == "released" and not self._phase_gate_released_logged:
                self._phase_gate_released_logged = True
                self.log(f"P0 test gate released peer {phase}.")
                self._record("test_gate_released", phase=phase)
        return self.coordinator.take_remote_block(phase)

    def phase_settled(self, phase):
        try:
            snapshot = self.coordinator.settle_phase(phase)
        except ProtocolError as exc:
            self._mark_failed(exc)
            return
        self.log(f"Local Switch link phase settled: {phase}.")
        self._record("local_phase_settled", phase=phase)
        if snapshot is not None:
            if self.failed is None:
                try:
                    self.transport.send("SNAPSHOT_READY", snapshot)
                except TransportError as exc:
                    self._mark_failed(exc)
            self.log("Local snapshot was fully presented by the RFU engine; waiting for the peer snapshot.")
            self._record("local_snapshot_ready", snapshot_id=snapshot["snapshot_id"],
                         digest=snapshot["digest"])

    def local_identity(self, *, version, language, player_id):
        versions = {0x4004: "FireRed", 0x4005: "LeafGreen"}
        languages = {2: "English", 3: "French", 4: "Italian", 5: "German", 7: "Spanish"}
        self.local_game_identity = {
            "version": int(version),
            "version_name": versions.get(int(version), f"unknown-0x{int(version):04x}"),
            "language": int(language),
            "language_name": languages.get(int(language), f"unknown-{int(language)}"),
            "child_player_id": int(player_id),
            "sent_parent_player_id": 0,
        }
        self.log("Local cartridge identity: "
                 f"{self.local_game_identity['version_name']} / "
                 f"{self.local_game_identity['language_name']}; "
                 f"child player_id={int(player_id)}, peer parent player_id=0.")
        self._record("local_game_identity", **self.local_game_identity)

    def local_link_state(self, state):
        if state not in {"waiting", "connected", "closing", "closed", "failed"}:
            raise ValueError("invalid local link state")
        if state == self.coordinator.local_link_state:
            return
        self.coordinator.local_link_state = state
        if self.failed is None:
            try:
                self.transport.send("LOCAL_LINK_STATE", {"state": state})
            except TransportError as exc:
                self._mark_failed(exc)
        self._record("local_link_state", state=state)

    def poll(self):
        for event in self.transport.poll():
            if event.kind == "error":
                self._mark_failed(event.error or "LAN transport failed")
                break
            try:
                self._handle_event(event)
            except (ProtocolError, TransportError, ValueError) as exc:
                self._mark_failed(exc)
                break
        if self.transport.error is not None:
            self._mark_failed(self.transport.error)
        if self.engine is not None:
            self.engine.resume_remote_phase()

    def _handle_event(self, event: TransportEvent):
        message = event.message
        if message is None:
            raise ProtocolError("transport delivered an empty event")
        if message.type == "PEER_BLOCK":
            if message.phase == "link_player":
                _peer, magic_ok = linkplayer.parse_block(
                    base64.b64decode(message.payload["data"], validate=True))
                if not magic_ok:
                    raise ProtocolError("peer LinkPlayer block has invalid GameFreak magic")
            added = self.coordinator.record_remote_message(message)
            if added:
                data = self.coordinator.remote_blocks[message.phase]
                digest = message.payload["digest"]
                self.log(f"LAN probe received peer {message.phase} block ({len(data)} bytes, sha256={digest}).")
                self._record("peer_block_received", phase=message.phase,
                             length=len(logical_bytes(message.phase, data)), digest=digest)
        elif message.type == "SNAPSHOT_READY":
            self.coordinator.record_remote_snapshot(message.payload)
            self.log("Peer reports its complete local snapshot; both sides can now cancel the probe.")
            self._record("peer_snapshot_ready", snapshot_id=message.payload["snapshot_id"],
                         digest=message.payload["digest"])
        elif message.type == "LOCAL_LINK_STATE":
            self.coordinator.remote_link_state = message.payload["state"]
            self.log(f"Peer local RFU state: {message.payload['state']}.")
            self._record("peer_link_state", state=message.payload["state"])
        elif message.type == "PROBE_STOP":
            self.coordinator.remote_stop_reason = message.payload["reason"]
            self.log(f"Peer requested probe stop ({message.payload['reason']}).")
            self._record("peer_stop", reason=message.payload["reason"])
        elif message.type == "ERROR":
            raise TransportError(f"peer reported {message.payload['code']}")
        else:
            raise ProtocolError(f"unexpected application message {message.type}")

    def stop(self, reason):
        if reason not in {"cancelled", "completed", "in_doubt", "link_failed"}:
            raise ValueError("invalid probe stop reason")
        if self.failed is None:
            self.transport.send("PROBE_STOP", {"reason": reason})
        self._record("probe_stop", reason=reason)

    def report(self):
        report = self.coordinator.report()
        report["lan_failure"] = self.failed
        report["journal_failure"] = self.journal_failure
        report["local_game_identity"] = self.local_game_identity
        return report
