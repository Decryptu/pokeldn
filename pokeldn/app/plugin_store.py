"""Installing, updating and removing `.pokeplugin` packages in the data folder's plugins/.

A package is a zip holding plugin.toml at its root or inside one top folder, beside the plugin's
module and files (docs/plugins.md, Packages). Nothing in a package runs before it is installed and
turned on.
"""
import ast
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import time
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from pokeldn import plugins
from pokeldn.app import archives

EXTENSION = "pokeplugin"
MAX_FILES = 2000
MAX_BYTES = 64 << 20
MAX_SOURCE = 512 << 10
ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
CONSENT = ".installed.json"     # written when the user accepted the risks for this plugin
SIGNATURE = "plugin.sig"         # the author's key and signature over every other file
SKIP = ("__pycache__", ".DS_Store", CONSENT, SIGNATURE)
SIGNED = b"pokeldn plugin signature 1\n"


class PackageError(Exception):
    """A file that is not an installable plugin; the message is shown to the user as it is."""


@dataclass
class Package:
    id: str
    name: str
    version: str
    api: tuple | None
    author: str = ""
    description: str = ""
    homepage: str = ""
    files: int = 0
    size: int = 0
    icon: bytes = b""
    source: str = ""
    prefix: str = ""                 # the top folder the files sit in, or ""
    members: list = field(default_factory=list)
    findings: list = field(default_factory=list)   # what its code does (scan)
    key: str = ""                    # the author's public key (base64), when signed
    updates: str = ""                # where its newer versions are published
    digest: str = ""
    library: str = ""                # the player-visible folder it keeps files in (plugins.library_name)


def _version(text: str) -> tuple:
    if not isinstance(text, str) or len(text) > 96:
        return ()
    parts = re.findall(r"\d+", text)[:4]
    return tuple(int(n) for n in parts) if all(len(n) <= 9 for n in parts) else ()


def compare(package: Package, installed: plugins.Plugin | None) -> str:
    """install, update, reinstall or downgrade."""
    if installed is None:
        return "install"
    new, old = _version(package.version), _version(installed.version)
    return "update" if new > old else "downgrade" if new < old else "reinstall"


def read(path: str) -> Package:
    try:
        return _read(path)
    except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError, ValueError, RecursionError) as error:
        raise PackageError(f"The plugin package could not be read ({error}).") from None


def _read(path: str) -> Package:
    """Reads and checks a package without extracting it."""
    try:
        if os.path.getsize(path) > MAX_BYTES + (1 << 20):
            raise PackageError("The package is too large to be a plugin.")
        archive = archives.open_zip(path, MAX_FILES)
    except (OSError, zipfile.BadZipFile) as error:
        raise PackageError(f"{os.path.basename(path)} is not a plugin package ({error}).") from None
    with archive:
        try:
            archives.bounded(((i.filename, i.file_size, i) for i in archive.infolist()),
                             MAX_FILES, MAX_BYTES, MAX_BYTES)
        except OSError as error:
            raise PackageError(f"The package holds an unsafe path or is too large: {error}") from None
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_BYTES:
            raise PackageError("The package is too large to be a plugin.")
        sources = [i for i in infos if i.filename.endswith(".py")]
        if any(i.file_size > MAX_SOURCE for i in sources) or sum(i.file_size for i in sources) > 8 << 20:
            raise PackageError("The package has too much Python source to review safely.")
        names = [i.filename for i in infos]
        for info in infos:
            parts = PurePosixPath(info.filename).parts
            if info.filename.startswith(("/", "\\")) or ".." in parts or ":" in info.filename \
                    or stat.S_ISLNK(info.external_attr >> 16):
                raise PackageError(f"The package holds an unsafe path: {info.filename}")
        tomls = [n for n in names if PurePosixPath(n).name == "plugin.toml" and len(PurePosixPath(n).parts) <= 2]
        if len(tomls) != 1:
            raise PackageError("The package has no plugin.toml at its top." if not tomls else
                               "The package holds several plugins; install them one by one.")
        prefix = str(PurePosixPath(tomls[0]).parent)
        prefix = "" if prefix == "." else prefix + "/"
        if any(not n.startswith(prefix) for n in names):
            raise PackageError("plugin.toml must sit at the top of the package, beside the plugin's files.")
        try:
            meta = tomllib.loads(archive.read(tomls[0]).decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise PackageError(f"plugin.toml does not parse: {error}") from None
        plugin_id = str(meta.get("id", ""))
        if not ID.fullmatch(plugin_id):
            raise PackageError("plugin.toml needs an id of lowercase letters, digits, dots, dashes or underscores.")
        api = plugins.parse_api(meta.get("api"))
        try:
            library = plugins.library_name(meta["library"]) if "library" in meta else ""
        except ValueError as error:
            raise PackageError(str(error)) from None
        state, message = plugins.compatibility(api)
        if state in ("newer", "older"):
            raise PackageError(message)
        module = str(meta.get("module", "plugin"))
        if "locale" in meta or "strings" in meta:
            from pokeldn.app.i18n import read_pack, read_resources
            try:
                read_pack(meta, lambda name: archive.read(prefix + name))
                read_resources(meta, lambda name: archive.read(prefix + name))
            except ValueError as error:
                raise PackageError(str(error)) from None
        elif f"{prefix}{module}.py" not in names:
            raise PackageError(f"The package has no {module}.py next to plugin.toml.")
        contents = {n: archive.read(n) for n in names}
        findings = scan(contents)
        key = verify(plugin_id, str(meta.get("version", "")),
                     {n[len(prefix):]: data for n, data in contents.items()})
        icon_name = f"{prefix}{meta.get('icon', 'icon.png')}"
        icon = archive.read(icon_name) if icon_name in names else b""
        return Package(plugin_id, str(meta.get("name", plugin_id)), str(meta.get("version", "")), api,
                       str(meta.get("author", "")), str(meta.get("description", "")),
                       str(meta.get("homepage", "")), len(infos), sum(i.file_size for i in infos), icon,
                       os.path.abspath(path), prefix, names, findings, key, str(meta.get("updates", "")),
                       hashlib.sha256(_manifest(plugin_id, str(meta.get("version", "")), contents)).hexdigest(),
                       library)


NETWORK = {"socket", "ssl", "urllib", "http", "requests", "httpx", "aiohttp", "websockets", "websocket", "ftplib",
           "smtplib", "poplib", "imaplib", "xmlrpc", "paramiko", "asyncssh"}
PROGRAMS = {"system", "popen", "startfile", "execv", "execve", "execl", "execlp", "execvp", "spawnv", "spawnl",
            "posix_spawn", "posix_spawnp"}
DELETES = {"remove", "unlink", "rmdir", "rmtree", "removedirs", "truncate"}
COMPILED = (".so", ".dylib", ".dll", ".pyd", ".exe", ".bin", ".jar")


def _manifest(plugin_id: str, version: str, files: dict) -> bytes:
    """What a signature covers: the plugin's id, version and every installed file's SHA-256."""
    lines = sorted(f"{hashlib.sha256(data).hexdigest()}  {name}" for name, data in files.items()
                   if name and not any(part in SKIP for part in PurePosixPath(name).parts))
    return SIGNED + f"{plugin_id}\n{version}\n".encode() + "\n".join(lines).encode()


def verify(plugin_id: str, version: str, files: dict) -> str:
    """The author's key (base64) when `files` (relative name -> bytes) carry a valid signature, ""
    when unsigned; a PackageError when the signature does not match the files."""
    if SIGNATURE not in files:
        return ""
    from Crypto.Signature import eddsa
    try:
        signed = json.loads(files[SIGNATURE])
        raw = base64.b64decode(signed["key"], validate=True)
        key = eddsa.import_public_key(raw)
        eddsa.new(key, "rfc8032").verify(_manifest(plugin_id, version, files),
                                         base64.b64decode(signed["signature"], validate=True))
    except (ValueError, KeyError, TypeError):
        raise PackageError("This plugin was changed after its author signed it, or its signature is damaged. "
                           "Get it again from its author.") from None
    return base64.b64encode(raw).decode()


def fingerprint(key: str) -> str:
    """A short name for an author's key, to compare with the one the author publishes."""
    text = base64.b32encode(hashlib.sha256(base64.b64decode(key)).digest()).decode()[:16]
    return "-".join(text[i:i + 4] for i in range(0, 16, 4))


def signing_key(path: str, create: bool = False):
    """The author's private key in `path` (PEM), made there first with `create`."""
    from Crypto.PublicKey import ECC
    if create and not os.path.exists(path):
        key = ECC.generate(curve="ed25519")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "x", encoding="utf-8") as out:
            out.write(key.export_key(format="PEM"))
        if os.name != "nt":
            os.chmod(path, 0o600)
        return key
    with open(path, encoding="utf-8") as source:
        return ECC.import_key(source.read())


def _sign(key, plugin_id: str, version: str, files: dict) -> bytes:
    from Crypto.Signature import eddsa
    raw = key.public_key().export_key(format="raw")
    signature = eddsa.new(key, "rfc8032").sign(_manifest(plugin_id, version, files))
    return json.dumps({"key": base64.b64encode(raw).decode(),
                       "signature": base64.b64encode(signature).decode()}).encode()


def _keys_file() -> Path:
    return plugins.folder() / ".keys.json"


def known_key(plugin_id: str) -> str:
    """The author's key the app remembers for this plugin since its first signed install."""
    try:
        keys = json.loads(_keys_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(keys.get(plugin_id, "")) if isinstance(keys, dict) else ""


def _remember(plugin_id: str, key: str) -> None:
    try:
        keys = json.loads(_keys_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        keys = {}
    keys[plugin_id] = key
    _keys_file().write_text(json.dumps(keys, indent=1), encoding="utf-8")


def trust(package: Package) -> str:
    """new (signed, first seen), same (the author of the copy seen before), changed (another key),
    dropped (unsigned where an earlier copy was signed) or unsigned."""
    known = known_key(package.id)
    if package.key:
        return "new" if not known else "same" if known == package.key else "changed"
    return "dropped" if known else "unsigned"


def scan(files: dict) -> list[str]:
    """What a plugin's Python files do that a player should know before installing, one line each.
    A reading of the source: it cannot prove a plugin safe, and code built at run time escapes it."""
    found: dict[str, None] = {}
    compiled = [n for n in files if n.lower().endswith(COMPILED)]
    for name, data in files.items():
        if not name.endswith(".py"):
            continue
        try:
            tree = ast.parse(data, name)
        except (SyntaxError, ValueError, RecursionError):
            found["Has Python files pokeldn cannot read"] = None
            continue
        for node in ast.walk(tree):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for module in modules:
                top = module.split(".")[0]
                if top in NETWORK:
                    found["Uses the internet or the network"] = None
                if top == "subprocess":
                    found["Starts other programs"] = None
                if top in ("ctypes", "cffi"):
                    found["Calls native code directly, which the guardrails cannot watch"] = None
            if isinstance(node, ast.Call):
                callee = node.func.attr if isinstance(node.func, ast.Attribute) else \
                    node.func.id if isinstance(node.func, ast.Name) else ""
                if callee in PROGRAMS:
                    found["Starts other programs"] = None
                if callee in DELETES:
                    found["Deletes files"] = None
                if callee in ("exec", "eval", "compile", "__import__") or \
                        (callee == "loads" and isinstance(node.func, ast.Attribute)
                         and getattr(node.func.value, "id", "") == "marshal"):
                    found["Runs code it builds while running, which this check cannot read"] = None
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                    ("prod.keys" in node.value or "title.keys" in node.value):
                found["Names your Switch keys file"] = None
    if compiled:
        found[f"Ships {len(compiled)} compiled file{'s' * (len(compiled) != 1)} this check cannot read"] = None
    return list(found)


def describe(plugin: plugins.Plugin) -> Package:
    """A plugin copied into the plugins folder by hand, read as a package would be."""
    files = {p.relative_to(plugin.folder).as_posix(): p.read_bytes() for p in plugin.folder.rglob("*")
             if p.is_file() and not any(part in ("__pycache__", ".DS_Store", CONSENT)
                                         for part in p.relative_to(plugin.folder).parts)}
    return Package(plugin.id, plugin.name, plugin.version, plugin.api, plugin.author, plugin.description,
                   plugin.homepage, len(files), sum(map(len, files.values())), findings=scan(files),
                   key=verify(plugin.id, plugin.version, files), updates=plugin.updates, library=plugin.library)


def installed(plugin_id: str) -> plugins.Plugin | None:
    folder = plugins.folder() / plugin_id
    return plugins._read_folder(folder) if (folder / "plugin.toml").is_file() else None


def consented(plugin: plugins.Plugin) -> bool:
    """True once the user accepted the risks for this plugin in the app."""
    return plugin.folder is not None and (plugin.folder / CONSENT).is_file()


def accept(plugin: plugins.Plugin, key: str = "") -> None:
    """Records the user's acceptance for a plugin that came in by hand, not through install, and the
    key that signed it."""
    if key:
        _remember(plugin.id, key)
    (plugin.folder / CONSENT).write_text(json.dumps({"accepted": time.strftime("%Y-%m-%d %H:%M"),
                                                     "source": "folder"}), encoding="utf-8")


def origin(plugin: plugins.Plugin) -> str:
    """The source listing a plugin was installed from (pokeldn.app.plugin_sources), or ""."""
    try:
        consent = json.loads((plugin.folder / CONSENT).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    return str(consent.get("origin", "")) if isinstance(consent, dict) else ""


def install(package: Package, origin: str = "") -> Path:
    """Extracts the package as plugins/<id>, replacing an installed copy only once the new one is
    whole; `origin` is the source listing it came from. The caller has shown the risks and the user
    accepted them."""
    current = read(package.source)
    if (current.id, current.version, current.key, current.digest) != (package.id, package.version, package.key, package.digest):
        raise PackageError("The package changed after it was checked.")
    package = current
    root = plugins.folder()
    root.mkdir(parents=True, exist_ok=True)
    target = root / package.id
    staging = root / f".staging-{package.id}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        with archives.open_zip(package.source, MAX_FILES) as archive:
            for name in package.members:
                relative = name[len(package.prefix):]
                if not relative or any(part in SKIP for part in PurePosixPath(relative).parts):
                    continue
                out = archives.destination(staging, relative)
                out.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, open(out, "wb") as dst:
                    archives.copy(src, dst, archive.getinfo(name).file_size)
        (staging / CONSENT).write_text(json.dumps({"accepted": time.strftime("%Y-%m-%d %H:%M"),
                                                   "source": os.path.basename(package.source),
                                                   "version": package.version,
                                                   **({"origin": origin} if origin else {})}), encoding="utf-8")
        old = root / f".old-{package.id}"
        shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            os.replace(target, old)
        os.replace(staging, target)
        shutil.rmtree(old, ignore_errors=True)
        if package.key:
            _remember(package.id, package.key)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target


def remove(plugin_id: str, data: bool = False) -> None:
    """Deletes plugins/<id>, and with `data` what it kept; a plugin elsewhere (POKELDN_PLUGINS, a
    package) is not the app's to delete."""
    root = plugins.folder().resolve()
    target = (root / plugin_id).resolve()
    if target.parent != root or not (target / "plugin.toml").is_file():
        raise PackageError("Only a plugin installed in the app can be removed here.")
    shutil.rmtree(target)
    from pokeldn.app import panels
    panels.forget(plugin_id)
    if data and ID.fullmatch(plugin_id):
        shutil.rmtree(plugins.data_folder(plugin_id), ignore_errors=True)


def kept_data(plugin_id: str) -> int:
    """The bytes a plugin keeps in its data folder."""
    folder = plugins.data_folder(plugin_id)
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else 0


def pack(folder: str, out: str, key=None) -> Package:
    """Writes a folder holding plugin.toml as a package, signed with the author's `key`, then reads it
    back as the app would. Hidden files and plugin.toml's `exclude` paths stay out."""
    source = Path(folder)
    meta = tomllib.loads((source / "plugin.toml").read_text(encoding="utf-8"))
    exclude = meta.get("exclude", [])
    exclude = [PurePosixPath(e).parts for e in exclude if isinstance(e, str) and e] if isinstance(exclude, list) else []

    def kept(parts: tuple) -> bool:
        return not any(part in SKIP or part.startswith(".") for part in parts) and \
            not any(parts[:len(e)] == e for e in exclude)
    files = {p.relative_to(source).as_posix(): p.read_bytes() for p in sorted(source.rglob("*"))
             if p.is_file() and kept(p.relative_to(source).parts)}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        if key is not None:
            archive.writestr(SIGNATURE, _sign(key, str(meta.get("id", "")), str(meta.get("version", "")), files))
    return read(out)


def size_text(size: int) -> str:
    return (f"{size} B" if size < 1024 else f"{size / 1024:.0f} KB" if size < 1 << 20 else
            f"{size / (1 << 20):.1f} MB" if size < 1 << 30 else f"{size / (1 << 30):.2f} GB")
