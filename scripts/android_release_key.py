#!/usr/bin/env python3
"""Make the Android app's release signing key and hand it to the release workflow.

Writes ~/.config/pokeldn/android-release.jks and its password beside it once, then stores both as the
repository secrets ANDROID_RELEASE_KEYSTORE and ANDROID_RELEASE_PASSWORD with gh. Keep the key: an
APK signed with another key does not install over one signed with this one.
"""
import argparse
import base64
import secrets
import subprocess
from pathlib import Path

HOME = Path.home() / ".config" / "pokeldn"
KEY = HOME / "android-release.jks"
PASSWORD = HOME / "android-release.password"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default="Decryptu/pokeldn")
    args = parser.parse_args()
    if not KEY.exists():
        HOME.mkdir(parents=True, exist_ok=True)
        word = secrets.token_hex(24)
        subprocess.run(["keytool", "-genkeypair", "-keystore", str(KEY), "-storetype", "PKCS12",
                        "-alias", "pokeldn", "-keyalg", "RSA", "-keysize", "4096", "-validity", "36500",
                        "-storepass", word, "-keypass", word, "-dname", "CN=pokeldn"], check=True)
        PASSWORD.write_text(word)
        KEY.chmod(0o600)
        PASSWORD.chmod(0o600)
    subprocess.run(["gh", "secret", "set", "ANDROID_RELEASE_KEYSTORE", "-R", args.repo],
                   input=base64.b64encode(KEY.read_bytes()), check=True)
    subprocess.run(["gh", "secret", "set", "ANDROID_RELEASE_PASSWORD", "-R", args.repo],
                   input=PASSWORD.read_bytes(), check=True)
    print(f"Release key {KEY} stored as {args.repo}'s ANDROID_RELEASE_* secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
