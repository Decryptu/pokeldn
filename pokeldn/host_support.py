import os


def resolve_keys(path):
    """Resolves ~ against SUDO_USER's home when launched through sudo."""
    expanded = os.path.expanduser(path)
    if os.path.exists(expanded):
        return expanded
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and path.startswith("~"):
        try:
            import pwd
            home = pwd.getpwnam(sudo_user).pw_dir
            candidate = (os.path.join(home, path[2:]) if path.startswith("~/")
                         else path.replace("~", home, 1))
            if os.path.exists(candidate):
                return candidate
        except (KeyError, ImportError):
            pass
    return expanded


def needs_root():
    from pokeldn.ldn.transport import board_radio
    return not board_radio() and (not hasattr(os, "geteuid") or os.geteuid() != 0)


def open_output(path, mode="w", **options):
    from pathlib import Path
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if "b" not in mode:
        options.setdefault("encoding", "utf-8")
    return target.open(mode, **options)


def write_file(path, data):
    with open_output(path, "w" if isinstance(data, str) else "wb") as stream:
        stream.write(data)
