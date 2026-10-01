import hashlib
import json

import pytest

from pokeldn.frlg.remote.coordinator import snapshot_digest
from pokeldn.frlg.remote.protocol import PHASE_ORDER, PHASE_SIZES, logical_bytes
from tools.frlg.validate_remote_p0_evidence import EvidenceError, validate_pair


RUN = "12" * 16
SNAPSHOT_A = "34" * 16
SNAPSHOT_B = "56" * 16


def _blocks(offset):
    return {
        phase: bytes([index + offset]) * PHASE_SIZES[phase]
        for index, phase in enumerate(PHASE_ORDER)
    }


def _phase_events(event, blocks):
    result = []
    for phase in PHASE_ORDER:
        data = logical_bytes(phase, blocks[phase])
        result.append({
            "run_id": RUN,
            "event": event,
            "phase": phase,
            "length": len(data),
            "digest": hashlib.sha256(data).hexdigest(),
        })
    return result


def _side(local, peer, *, side, corrupt=None):
    local_snapshot_id = SNAPSHOT_A if side == "A" else SNAPSHOT_B
    peer_snapshot_id = SNAPSHOT_B if side == "A" else SNAPSHOT_A
    local_digest = snapshot_digest(local)
    peer_digest = snapshot_digest(peer)
    events = _phase_events("local_block_received", local)
    events.extend(_phase_events("peer_block_received", peer))
    events.extend({"run_id": RUN, "event": "local_phase_settled", "phase": phase}
                  for phase in PHASE_ORDER)
    events.extend([
        {"run_id": RUN, "event": "local_snapshot_ready",
         "snapshot_id": local_snapshot_id, "digest": local_digest},
        {"run_id": RUN, "event": "peer_snapshot_ready",
         "snapshot_id": peer_snapshot_id, "digest": peer_digest},
        {"run_id": RUN, "event": "probe_stop", "reason": "cancelled"},
        {"run_id": RUN, "event": "probe_summary",
         "local_link_state": "closed",
         "local_close_confirmed": True,
         "local_phases_settled": list(PHASE_ORDER),
         "local_snapshot_id": local_snapshot_id,
         "local_snapshot_digest": local_digest,
         "remote_snapshot_id": peer_snapshot_id,
         "remote_snapshot_digest": peer_digest,
         "both_snapshots_ready": True,
         "lan_failure": None,
         "journal_failure": None,
         "local_game_identity": {"sent_parent_player_id": 0},
         "p0_command_audit": {
             "probe_only": True,
             "outbound_linkcmd_counts": {},
             "refused_console_command_counts": {},
             "start_trade_attempts_refused": 0,
             "commit_attempts_refused": 0,
             "commits": 0,
             "received_mon_count": 0,
             "animation_state_entries": 0,
             "save_state_entries": 0,
         }},
    ])
    if corrupt == "start":
        events[-1]["p0_command_audit"]["outbound_linkcmd_counts"]["START_TRADE"] = 1
    elif corrupt == "sensitive":
        events[0]["data"] = "raw-block"
    elif corrupt == "digest":
        events[0]["digest"] = "0" * 64
    elif corrupt == "stop":
        events[-2]["reason"] = "link_failed"
    return events


def _write(path, events):
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def test_p0_evidence_validator_accepts_complete_matching_pair(tmp_path):
    blocks_a = _blocks(1)
    blocks_b = _blocks(20)
    path_a, path_b = tmp_path / "A.jsonl", tmp_path / "B.jsonl"
    _write(path_a, _side(blocks_a, blocks_b, side="A"))
    _write(path_b, _side(blocks_b, blocks_a, side="B"))

    assert validate_pair(path_a, path_b) == RUN


@pytest.mark.parametrize("side,corrupt,error", [
    ("A", "start", "trade start"),
    ("A", "sensitive", "forbidden field"),
    ("A", "digest", "digests differ for link_player"),
    ("B", "stop", "did not request a cancelled stop"),
])
def test_p0_evidence_validator_rejects_incomplete_or_unsafe_evidence(
        tmp_path, side, corrupt, error):
    blocks_a = _blocks(1)
    blocks_b = _blocks(20)
    events_a = _side(blocks_a, blocks_b, side="A", corrupt=corrupt if side == "A" else None)
    events_b = _side(blocks_b, blocks_a, side="B", corrupt=corrupt if side == "B" else None)
    path_a, path_b = tmp_path / "A.jsonl", tmp_path / "B.jsonl"
    _write(path_a, events_a)
    _write(path_b, events_b)

    with pytest.raises(EvidenceError, match=error):
        validate_pair(path_a, path_b)
