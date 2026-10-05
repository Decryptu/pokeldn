#!/usr/bin/env bash
set -eu

if [[ $# -lt 1 || $# -gt 2 || ! $1 =~ ^[[:xdigit:]]{8}$ ]]; then
    echo "usage: $0 8-DIGIT-HEX-SEED [original|full|handoff20|seq12forret|seq12forretfull|seq1112forret|stop18|stop20|stop21|stop22|stop23|delay23|skip23]" >&2
    exit 2
fi

seed=${1^^}
mode=${2:-full}
script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
cd "$script_dir"

python_bin="$script_dir/.venv/bin/python"
if [[ ! -x $python_bin ]]; then
    echo "missing $python_bin; create bin/.venv and install ../requirements.txt first" >&2
    exit 1
fi

export POKELDN_RADIO=esp32:/dev/ttyACM0

raid_patch_args=(
    --raid-context raid_context_4star_paldea.json
    --raid-runtime-clear-commands
)
if [[ $seed == BD13FB43 ]]; then
    # The reference seed is replayed byte-for-byte as the control.  Running it through the
    # provisional encounter generator can select a different table entry, and patch_boss already
    # treats equal source/target seeds as an exact no-op.
    raid_patch_args=()
fi

capture_suffix=full
replay_control_args=()
replay_repair_args=(--raid-replay-repair-victory-gap)
case $mode in
    original)
        if [[ $seed != BD13FB43 ]]; then
            echo "original mode requires the captured Growlithe seed BD13FB43" >&2
            exit 2
        fi
        capture_suffix=original_unchanged
        replay_repair_args=()
        ;;
    full) ;;
    handoff20)
        capture_suffix=handoff_after_20
        replay_control_args=(--raid-replay-stop-after-seq 20
                             --raid-replay-disconnect-after-stop 2)
        ;;
    seq12forret)
        capture_suffix=seq12_forretress_11_178_handoff20
        replay_control_args=(--raid-replay-seq12-overlay-trace
                             tera_raid_retail_controlled_tinkatink_first_moves.jsonl
                             --raid-replay-stop-after-seq 20
                             --raid-replay-disconnect-after-stop 30)
        ;;
    seq12forretfull)
        capture_suffix=seq12_forretress_full_suffix_handoff20
        replay_control_args=(--raid-replay-seq12-overlay-trace
                             tera_raid_retail_controlled_tinkatink_first_moves.jsonl
                             --raid-replay-seq12-overlay-full
                             --raid-replay-stop-after-seq 20
                             --raid-replay-disconnect-after-stop 30)
        ;;
    seq1112forret)
        capture_suffix=seq11_12_forretress_template_pawniard_pk9_handoff20
        replay_control_args=(--raid-replay-seq11-12-template-trace
                             tera_raid_retail_controlled_tinkatink_first_moves.jsonl
                             --raid-replay-stop-after-seq 20
                             --raid-replay-disconnect-after-stop 30)
        ;;
    stop18|stop20|stop21|stop22|stop23)
        stop_sequence=${mode#stop}
        capture_suffix="stop_after_${stop_sequence}"
        replay_control_args=(--raid-replay-stop-after-seq "$stop_sequence")
        ;;
    delay23)
        capture_suffix=delay_23_5s
        replay_control_args=(--raid-replay-delay-seq23 5)
        ;;
    skip23)
        capture_suffix=skip_23_send_24
        replay_control_args=(--raid-replay-skip-seq23 --raid-replay-stop-after-seq 24)
        ;;
    *)
        echo "unknown mode: $mode" >&2
        exit 2
        ;;
esac

exec "$python_bin" -u sv_host.py \
    --keys /home/ismail/Downloads/switchkeys.io-v22.5.0/prod.keys \
    --channel 1 \
    --scene-id 7 \
    --max-participants 4 \
    --ssid 75db0fb3342cee600d3549e90d88b56f \
    --mac a4:38:cc:eb:6d:5a \
    --host-var 0x7727 \
    --code 4970 \
    --game-data 343937300000000000000000000000000000000000000000000000000000000000aa281104000000 \
    --net-unicast \
    --scarlet-response \
    --session-flags 0 \
    --session-packet-id 1 \
    --no-session-ack \
    --join-seq 0 \
    --update-seq 0 \
    --update-delay 0.02 \
    --rtt-probe \
    --clock \
    --net-stations 4 \
    --record-delay 0.100 \
    --record-spacing 0.003 \
    --record-set tera_raid_retail_victory_full_records \
    --preserve-records \
    --host-player-id 100036df3a8d57687a5361855a6377a1 \
    --host-player-name ' ' \
    --raid \
    --raid-replay-trace tera_raid_retail_victory_full.jsonl \
    --raid-replay-interactive \
    --raid-base-seed BD13FB43 \
    --raid-seed "$seed" \
    "${raid_patch_args[@]}" \
    "${replay_repair_args[@]}" \
    "${replay_control_args[@]}" \
    --seconds 600 \
    --capture "tera_raid_seed_${seed}_${capture_suffix}_ch1_4970.jsonl"
