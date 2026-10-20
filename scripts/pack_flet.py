#!/usr/bin/env python3
"""Run Flet's packer while preserving the macOS viewer's file-picker permissions."""
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def assemble_macos_view(app_path, tar_path):
    from flet_cli.__pyinstaller.utils import normalize_tar_entry

    # Flet 1.0.2 macos_utils.assemble_app_bundle drops sealed entitlements.
    # The file picker requires user-selected.read-write; see docs/gui.md.
    result = subprocess.run(["codesign", "--display", "--entitlements", "-", "--xml", app_path],
                            capture_output=True, check=True)
    entitlements = plistlib.loads(result.stdout)
    if not entitlements.get("com.apple.security.files.user-selected.read-write"):
        raise SystemExit("The Flet macOS viewer lacks its file-picker entitlement.")
    with tempfile.TemporaryDirectory(prefix="pokeldn-sign-") as folder:
        path = Path(folder) / "entitlements.plist"
        path.write_bytes(plistlib.dumps(entitlements))
        subprocess.run(["codesign", "--force", "--sign", "-", "--entitlements", str(path), app_path],
                       check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", app_path], check=True)
    # xz under Flet's .tar.gz name, 30 percent smaller than gzip; gui/flet_client.py lets Flet open it.
    with tarfile.open(tar_path, "w:xz") as archive:
        archive.add(app_path, arcname=Path(app_path).name, filter=normalize_tar_entry)
    shutil.rmtree(app_path)


if __name__ == "__main__":
    if sys.platform == "darwin":
        from flet_cli.__pyinstaller import macos_utils
        macos_utils.assemble_app_bundle = assemble_macos_view
    from flet_cli.cli import main
    main()
