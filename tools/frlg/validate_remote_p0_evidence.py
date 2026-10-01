#!/usr/bin/env python3
"""Validate the machine-checkable portions of a pair of FRLG P0 JSONL journals."""

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pokeldn.frlg.remote.protocol import PHASE_ORDER, PHASE_SIZES


FORBIDDEN_FIELDS = {
    "data", "room_key", "pokemon", "pokemon_bytes", "prod.keys", "prod_keys",
}
HEX_128 = re.compile(r"[0-9a-fA-F]{32}\Z")
HEX_256 = re.compile(r"[0-9a-fA-F]{64}\Z")


class EvidenceError(ValueError):
    pass


def _is_hex(value, pattern):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _reject_sensitive_fields(value, location="record"):
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() in FORBIDDEN_FIELDS:
                raise EvidenceError(f"{location} contains forbidden field {key!r}")
            _reject_sensitive_fields(nested, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_fields(nested, f"{location}[{index}]")


def read_journal(path):
    path = Path(path)
    if not path.is_file():
        raise EvidenceError(f"journal does not exist: {path}")
    records = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise EvidenceError(f"cannot read {path}: {exc}") from exc
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise EvidenceError(f"{path}:{number} is a blank JSONL record")
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"{path}:{number} is invalid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise EvidenceError(f"{path}:{number} must be a JSON object")
        _reject_sensitive_fields(record, f"{path.name}:{number}")
        if not _is_hex(record.get("run_id"), HEX_128):
            raise EvidenceError(f"{path}:{number} has an invalid run_id")
        records.append(record)
    if not records:
        raise EvidenceError(f"journal is empty: {path}")
    run_ids = {record["run_id"] for record in records}
    if len(run_ids) != 1:
        raise EvidenceError(f"{path} contains multiple run IDs")
    return records


def _single(records, event, *, required=True):
    matches = [record for record in records if record.get("event") == event]
    if not matches and required:
        raise EvidenceError(f"missing {event} record")
    if len(matches) > 1:
        raise EvidenceError(f"expected one {event} record, found {len(matches)}")
    return matches[0] if matches else None


def _phase_records(records, event):
    matches = [record for record in records if record.get("event") == event]
    positions = []
    seen = {}
    for record in matches:
        phase = record.get("phase")
        if phase not in PHASE_ORDER:
            raise EvidenceError(f"{event} contains an unknown phase {phase!r}")
        positions.append(PHASE_ORDER.index(phase))
        expected_length = PHASE_SIZES[phase] - (140 if phase == "link_player" else 0)
        if record.get("length") != expected_length:
            raise EvidenceError(f"{event} {phase} length must be {expected_length}")
        digest = record.get("digest")
        if not _is_hex(digest, HEX_256):
            raise EvidenceError(f"{event} {phase} has an invalid digest")
        if phase in seen and seen[phase] != digest:
            raise EvidenceError(f"{event} repeated {phase} with different digests")
        seen[phase] = digest
    if positions != sorted(positions):
        raise EvidenceError(f"{event} phases are out of order")
    missing = [phase for phase in PHASE_ORDER if phase not in seen]
    if missing:
        raise EvidenceError(f"{event} is missing phases: {', '.join(missing)}")
    return seen


def _check_snapshot_record(records, event, snapshot_id, digest):
    record = _single(records, event)
    if record.get("snapshot_id") != snapshot_id or record.get("digest") != digest:
        raise EvidenceError(f"{event} does not match the final summary")
    if not _is_hex(snapshot_id, HEX_128):
        raise EvidenceError(f"{event} has an invalid snapshot ID")
    if not _is_hex(digest, HEX_256):
        raise EvidenceError(f"{event} has an invalid snapshot digest")


def _check_side(records, side):
    summary = _single(records, "probe_summary")
    if summary.get("run_id") != records[0]["run_id"]:
        raise EvidenceError(f"{side} summary run_id does not match its journal")
    if summary.get("lan_failure") is not None:
        raise EvidenceError(f"{side} summary records a LAN failure")
    if summary.get("journal_failure") is not None:
        raise EvidenceError(f"{side} summary records a journal failure")
    if summary.get("local_link_state") != "closed" or summary.get(
            "local_close_confirmed") is not True:
        raise EvidenceError(f"{side} did not record a confirmed local link close")
    stop = _single(records, "probe_stop")
    if stop.get("reason") != "cancelled":
        raise EvidenceError(f"{side} did not request a cancelled stop")
    if summary.get("both_snapshots_ready") is not True:
        raise EvidenceError(f"{side} did not receive both complete snapshots")
    if summary.get("local_phases_settled") != list(PHASE_ORDER):
        raise EvidenceError(f"{side} summary is missing settled phases")

    identity = summary.get("local_game_identity")
    if not isinstance(identity, dict) or identity.get("sent_parent_player_id") != 0:
        raise EvidenceError(f"{side} is missing its local game identity audit")
    audit = summary.get("p0_command_audit")
    if not isinstance(audit, dict) or audit.get("probe_only") is not True:
        raise EvidenceError(f"{side} is missing its P0 command audit")
    counts = audit.get("outbound_linkcmd_counts")
    if not isinstance(counts, dict):
        raise EvidenceError(f"{side} has an invalid outbound command audit")
    if counts.get("START_TRADE", 0) or counts.get("CONFIRM_FINISH_TRADE", 0):
        raise EvidenceError(f"{side} recorded a trade start or finish command")
    for field in (
            "start_trade_attempts_refused", "commit_attempts_refused", "commits",
            "received_mon_count", "animation_state_entries", "save_state_entries"):
        if audit.get(field) != 0:
            raise EvidenceError(f"{side} P0 audit expected {field}=0")

    local_blocks = _phase_records(records, "local_block_received")
    peer_blocks = _phase_records(records, "peer_block_received")
    settled = [record.get("phase") for record in records
               if record.get("event") == "local_phase_settled"]
    if settled != list(PHASE_ORDER):
        raise EvidenceError(f"{side} does not have exactly seven ordered settle records")

    _check_snapshot_record(records, "local_snapshot_ready",
                           summary.get("local_snapshot_id"),
                           summary.get("local_snapshot_digest"))
    _check_snapshot_record(records, "peer_snapshot_ready",
                           summary.get("remote_snapshot_id"),
                           summary.get("remote_snapshot_digest"))
    return summary, local_blocks, peer_blocks


def validate_pair(path_a, path_b):
    records_a = read_journal(path_a)
    records_b = read_journal(path_b)
    if records_a[0]["run_id"] != records_b[0]["run_id"]:
        raise EvidenceError("A and B journals have different run IDs")
    summary_a, local_a, peer_a = _check_side(records_a, "A")
    summary_b, local_b, peer_b = _check_side(records_b, "B")

    for phase in PHASE_ORDER:
        if local_a[phase] != peer_b[phase]:
            raise EvidenceError(f"A local and B peer digests differ for {phase}")
        if local_b[phase] != peer_a[phase]:
            raise EvidenceError(f"B local and A peer digests differ for {phase}")

    if (summary_a["local_snapshot_id"], summary_a["local_snapshot_digest"]) != (
            summary_b["remote_snapshot_id"], summary_b["remote_snapshot_digest"]):
        raise EvidenceError("A local snapshot does not match B's received snapshot")
    if (summary_b["local_snapshot_id"], summary_b["local_snapshot_digest"]) != (
            summary_a["remote_snapshot_id"], summary_a["remote_snapshot_digest"]):
        raise EvidenceError("B local snapshot does not match A's received snapshot")
    return records_a[0]["run_id"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", required=True, help="PC A events.jsonl")
    parser.add_argument("--b", required=True, help="PC B events.jsonl")
    args = parser.parse_args(argv)
    try:
        run_id = validate_pair(args.a, args.b)
    except EvidenceError as exc:
        print(f"P0 evidence check failed: {exc}", file=sys.stderr)
        return 1
    print(f"P0 journal evidence checks passed for run {run_id}.")
    print("This does not verify Switch screen recordings or other physical-console evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
