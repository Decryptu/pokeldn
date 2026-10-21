"""Newer versions of installed plugins, from the address each names in plugin.toml's `updates`: a
GitHub repository's latest release, or a JSON file {"version", "url", "page"}. Nothing installs
without the risk screen (docs/plugins.md, Updates)."""
from pokeldn.app.i18n import message_ref as _message
import hashlib
import re
import shutil
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from pokeldn import plugins
from pokeldn.app import plugin_store, update

GITHUB = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?")


@dataclass(frozen=True)
class Available:
    plugin: str
    version: str
    download: str
    page: str = ""
    sha256: str = ""        # what a source listing says the package hashes to
    source: str = ""        # the source listing that offered it


def allowed(url: str) -> bool:
    """HTTPS, or HTTP to this computer while an author tests."""
    try:
        if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 32 for c in url):
            return False
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost"))


def latest(url: str) -> tuple[str, str, str]:
    """(version, package URL, page) the address publishes; an OSError when it answers nothing usable."""
    if not allowed(url):
        raise OSError(_message('core.pokeldn.app.plugin_updates.value0_is_not_an_https_address_6582ba80', value0=url))
    repo = GITHUB.fullmatch(url)
    if repo:
        reply = update.github_json(f"https://api.github.com/repos/{repo[1]}/{repo[2]}/releases/latest")
        if not isinstance(reply, dict):
            raise OSError(_message('core.pokeldn.app.plugin_updates.github_sent_no_release_f915bfab'))
        assets = [a.get("browser_download_url") for a in reply.get("assets") or [] if isinstance(a, dict)
                  and str(a.get("name", "")).endswith(f".{plugin_store.EXTENSION}")]
        version = str(reply.get("tag_name", "")).removeprefix("v")
        download, page = (assets[0] if assets else ""), str(reply.get("html_url", ""))
    else:
        reply = update.github_json(url, what="plugin version")
        if not isinstance(reply, dict):
            raise OSError(_message('core.pokeldn.app.plugin_updates.no_plugin_version_e1d38f95'))
        version, download, page = str(reply.get("version", "")), str(reply.get("url", "")), str(reply.get("page", ""))
    if not version or len(version) > 96 or not isinstance(download, str) or not allowed(download):
        raise OSError(_message('core.pokeldn.app.plugin_updates.value0_names_no_value1_to_download_4b8e04c1', value0=url, value1=plugin_store.EXTENSION))
    return version, download, page


def check(found: list[plugins.Plugin], listings: list | None = None) -> dict[str, Available]:
    """The installed plugins with a newer version published, in a followed source's listing or at
    the plugin's own `updates` address; an address that fails is skipped."""
    from pokeldn.app import plugin_sources
    out = plugin_sources.updates(found, listings or [])
    for plugin in found:
        local = plugin.folder is not None and plugin.folder.parent == plugins.folder()
        if not (local and plugin.updates and plugin.version) or plugin.id in out:
            continue
        try:
            version, download, page = latest(plugin.updates)
        except OSError:
            continue
        if plugin_store._version(version) > plugin_store._version(plugin.version):
            out[plugin.id] = Available(plugin.id, version, download, page)
    return out


def download(available: Available, folder: Path) -> Path:
    """Fetches the package into an emptied `folder`; an OSError past the package size limit."""
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    if not plugin_store.ID.fullmatch(available.plugin) or not allowed(available.download):
        raise OSError(_message('core.pokeldn.app.plugin_updates.the_plugin_download_is_invalid_ff19ebf1'))
    dest = folder / f"{available.plugin}.{plugin_store.EXTENSION}"
    done, digest = 0, hashlib.sha256()
    try:
        with update._open(available.download) as reply, dest.open("wb") as out:
            for chunk in update.chunks(reply, 60):
                done += len(chunk)
                if done > plugin_store.MAX_BYTES:
                    raise OSError(_message('core.pokeldn.app.plugin_updates.the_download_is_too_large_to_be_a_plugin_7ab80da8'))
                digest.update(chunk)
                out.write(chunk)
        if available.sha256 and digest.hexdigest() != available.sha256:
            raise OSError(_message('core.pokeldn.app.plugin_updates.the_download_is_not_the_file_its_source_lists_it_360fcb16'))
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return dest
