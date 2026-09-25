"""Static coverage for Raspberry Pi deployment tooling.

The scripts make privileged and hardware-specific changes at runtime, so these
tests check their safety boundaries without attempting to run them on a desktop.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _text(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_pi_scripts_are_present_and_strict():
    for name in (
            "setup_pi.sh", "preflight_pi.sh", "run_mystery_gift.sh",
            "update_pi.sh", "deploy_pi.sh"):
        text = _text(f"scripts/{name}")
        assert text.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in text


def test_preflight_validates_tplink_driver_modes_and_key_permissions():
    text = _text("scripts/preflight_pi.sh")
    assert "/usr/sbin" in text
    assert "/sbin" in text
    assert "2357:012d" in text
    assert "rtw88_8822bu" in text
    assert "AP mode" in text
    assert "monitor mode" in text
    assert "load_host_file_config_from_argv" in text
    assert "skip_encryption" in text
    assert "accept_decrypted_ccmp" in text
    assert "USE_EXPLICIT_PHY" in text
    assert "mt76x0u requires accept_decrypted_ccmp=false" in text
    assert "named adapter is bypassed" in text
    assert "mt7601u AP-mode DKMS module is installed" in text
    assert "stat -c '%a'" in text
    assert '"$PROJECT_ROOT" "$@"' in text

    run = _text("scripts/run_mystery_gift.sh")
    assert 'preflight_pi.sh" "$@"' in run
    assert "-h|--help|--print-effective-config" in run
    assert run.index("-h|--help|--print-effective-config") < \
        run.index('preflight_pi.sh" "$@"')
    assert "--end-on-success" in run
    assert "--idle-timeout \"$IDLE_TIMEOUT_SECONDS\"" in run
    assert "--attempt-log-dir \"$ATTEMPT_LOG_DIR\"" in run
    assert "secrets.randbelow(65536)" in run
    assert "Restarting after successful distribution" not in run
    assert "Restarting after %s" in run

    ignore = _text(".gitignore")
    assert "logs/" in ignore


def test_deployment_requires_clean_committed_state_and_fast_forward_only():
    text = _text("scripts/deploy_pi.sh")
    assert "status --porcelain --untracked-files=all" in text
    assert "git init --bare" in text
    assert "HEAD:refs/heads/$BRANCH" in text
    assert "git clone --branch" in text
    assert "update_pi.sh" in text
    assert "--install-mt7601u-ap" in text
    assert "test_switch_key_installer.py" in text
    assert "git reset" not in text
    assert "rsync" in text  # documented as deliberately not used

    update = _text("scripts/update_pi.sh")
    assert "merge --ff-only FETCH_HEAD" in update
    assert "git reset" not in update
    assert "MT7601U DKMS source changed" in update
