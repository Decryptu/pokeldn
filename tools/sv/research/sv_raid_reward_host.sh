#!/usr/bin/env bash
set -eu

if [[ $# -ne 2 ]]; then
    echo "usage: $0 8-DIGIT-FIGHT-SEED REWARD-PROFILE.json" >&2
    exit 2
fi

script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
fight_seed=${1^^}
profile=$2
if [[ ! $fight_seed =~ ^[[:xdigit:]]{8}$ ]]; then
    echo "fight seed must be exactly eight hexadecimal digits" >&2
    exit 2
fi
if [[ $profile != /* ]]; then
    profile="$(pwd)/$profile"
fi
if [[ ! -f $profile ]]; then
    echo "reward profile not found: $profile" >&2
    exit 2
fi

python_bin="$script_dir/.venv/bin/python"
if [[ ! -x $python_bin ]]; then
    echo "missing $python_bin; install the project environment first" >&2
    exit 1
fi

export POKELDN_RADIO=${POKELDN_RADIO:-esp32:/dev/ttyACM0}
keys=${POKELDN_KEYS:-/home/ismail/Downloads/switchkeys.io-v22.5.0/prod.keys}
cd "$script_dir"

exec "$python_bin" -u sv_raid_host.py \
    --keys "$keys" \
    --raid-seed "$fight_seed" \
    --profile "$profile"
