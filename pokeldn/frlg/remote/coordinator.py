"""Small, socket-free stage coordinator for the trade-disabled P0 probe."""

import base64
import hashlib
import secrets

from pokeldn.frlg.remote.protocol import PHASE_ORDER, ProtocolError, logical_bytes


def snapshot_digest(blocks):
    digest = hashlib.sha256(b"pokeldn/frlg/remote/snapshot/v1\0")
    for phase in PHASE_ORDER:
        data = logical_bytes(phase, blocks[phase])
        name = phase.encode("ascii")
        digest.update(len(name).to_bytes(2, "big"))
        digest.update(name)
        digest.update(len(data).to_bytes(4, "big"))
        digest.update(data)
    return digest.hexdigest()


class ProbeCoordinator:
    """Tracks one ordered local snapshot and one ordered peer snapshot per run."""

    def __init__(self, run_id):
        self.run_id = run_id
        self.local_blocks = {}
        self.remote_blocks = {}
        self._remote_delivered = set()
        self.local_settled = set()
        self.local_snapshot_id = None
        self.local_snapshot_digest = None
        self.remote_snapshot = None
        self.local_link_state = "waiting"
        self.remote_link_state = "waiting"
        self.remote_stop_reason = None

    def record_local_block(self, phase, data):
        raw = bytes(data)
        logical_bytes(phase, raw)
        if phase in self.local_blocks:
            if self.local_blocks[phase] != raw:
                raise ProtocolError(f"local {phase} block changed within one probe run")
            return False
        expected = PHASE_ORDER[len(self.local_blocks)] if len(self.local_blocks) < len(PHASE_ORDER) else None
        if phase != expected:
            raise ProtocolError(f"local data phase {phase} arrived out of order")
        self.local_blocks[phase] = raw
        return True

    def record_remote_message(self, message):
        phase = message.phase
        data = base64.b64decode(message.payload["data"], validate=True)
        if phase in self.remote_blocks:
            if self.remote_blocks[phase] != data:
                raise ProtocolError(f"peer retransmitted different {phase} bytes")
            return False
        expected = PHASE_ORDER[len(self.remote_blocks)] if len(self.remote_blocks) < len(PHASE_ORDER) else None
        if phase != expected:
            raise ProtocolError(f"peer data phase {phase} arrived out of order")
        self.remote_blocks[phase] = data
        return True

    def take_remote_block(self, phase):
        if phase not in self.remote_blocks or phase in self._remote_delivered:
            return None
        self._remote_delivered.add(phase)
        return self.remote_blocks[phase]

    def settle_phase(self, phase):
        if phase not in self.local_blocks or phase not in self._remote_delivered:
            raise ProtocolError(f"cannot settle {phase} before both blocks reached this Switch")
        self.local_settled.add(phase)
        if (len(self.local_settled) == len(PHASE_ORDER)
                and self.local_snapshot_id is None):
            self.local_snapshot_id = secrets.token_hex(16)
            self.local_snapshot_digest = snapshot_digest(self.local_blocks)
            return {
                "snapshot_id": self.local_snapshot_id,
                "digest": self.local_snapshot_digest,
                "phases": list(PHASE_ORDER),
            }
        return None

    def record_remote_snapshot(self, payload):
        if tuple(self.remote_blocks) != PHASE_ORDER:
            raise ProtocolError("peer declared a snapshot before all seven data blocks arrived")
        expected_digest = snapshot_digest(self.remote_blocks)
        if payload["digest"] != expected_digest:
            raise ProtocolError("peer snapshot digest does not match its received data blocks")
        value = (payload["snapshot_id"], payload["digest"])
        if self.remote_snapshot is not None and self.remote_snapshot != value:
            raise ProtocolError("peer sent conflicting snapshot identities")
        self.remote_snapshot = value

    @property
    def both_snapshots_ready(self):
        return self.local_snapshot_id is not None and self.remote_snapshot is not None

    def report(self):
        return {
            "run_id": self.run_id,
            "local_link_state": self.local_link_state,
            "remote_link_state": self.remote_link_state,
            "local_phases_settled": [p for p in PHASE_ORDER if p in self.local_settled],
            "local_snapshot_id": self.local_snapshot_id,
            "local_snapshot_digest": self.local_snapshot_digest,
            "remote_snapshot_id": (self.remote_snapshot[0] if self.remote_snapshot else None),
            "remote_snapshot_digest": (self.remote_snapshot[1] if self.remote_snapshot else None),
            "both_snapshots_ready": self.both_snapshots_ready,
            "remote_stop_reason": self.remote_stop_reason,
        }
