"""The Plugins page: add a .pokeplugin, turn plugins on and off, update and remove them, pick a radio.
Every install shows the risks and waits for the user's acceptance (docs/plugins.md)."""
from pokeldn.app.i18n import t as tr
import os
import shutil
import threading
import time
from pathlib import Path

import flet as ft

from gui import drop
from gui import theme as t
from gui.views.widgets import open_folder
from gui.localization import translate
from pokeldn import plugins
from pokeldn.ldn import radios
from pokeldn.app import plugin_sources as sources
from pokeldn.app import library
from pokeldn.app import plugin_store as store
from pokeldn.app.paths import SESSION

ACTIONS = {"install": tr('plugins.install_569ca4', 'Install'), "update": tr('plugins.update_c1c100', 'Update'), "reinstall": tr('plugins.reinstall_c630a7', 'Reinstall'), "downgrade": tr('plugins.install_older_version_02704a', 'Install older version')}
RISKS = (
    tr('plugins.it_runs_as_a_program_on_this_computer_with_your_account_b7e17e', "It runs as a program on this computer, with your account's access to every file, your prod.keys included."),
    tr('plugins.it_can_use_the_network_your_board_and_the_sessions_you__57a803', 'It can use the network, your board and the sessions you start.'),
    tr('plugins.pokeldn_s_guardrails_stop_a_plugin_deleting_or_overwrit_183f30', "pokeldn's guardrails stop a plugin deleting or overwriting your files and running erase commands, but a plugin written to get around them can."),
    tr('plugins.pokeldn_does_not_review_or_support_plugins_and_cannot_u_37d86b', 'pokeldn does not review or support plugins, and cannot undo what one does.'),
)


def plugin_icon(source: str | bytes = "", size: int = 48) -> ft.Control:
    """The plugin's own image, or the blocks mark on the brand gradient."""
    if isinstance(source, str) and source:
        try:
            source = Path(source).read_bytes()
        except OSError:
            source = b""
    if source:
        image = ft.Image(src=t.image_src(source), width=size, height=size, fit=ft.BoxFit.CONTAIN,
                         filter_quality=ft.FilterQuality.NONE)
        return ft.Container(image, width=size, height=size, border_radius=size * 0.22,
                            clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
    return ft.Container(t.tinted(t.pixel_icon("blocks", size=24 if size < 48 else 48), t.BRAND_BLUE),
                        width=size, height=size, border_radius=size * 0.22, alignment=ft.Alignment.CENTER,
                        bgcolor=ft.Colors.with_opacity(0.08, "#FFFFFF"))


def checkbox(label: str, value: bool, on_change) -> ft.Container:
    """A whole-row tick box in the app's pixel style."""
    state = {"on": value}
    mark = t.pixel_icon("checkbox-on" if value else "checkbox", color=t.BLUE if value else t.MUTED)

    def toggle(e):
        state["on"] = not state["on"]
        mark.src = f"icons/{'checkbox-on' if state['on'] else 'checkbox'}.svg"
        mark.color = t.BLUE if state["on"] else t.MUTED
        mark.update()
        on_change(state["on"])

    return ft.Container(ft.Row([mark, t.text(label, 13, expand=True)], spacing=10,
                               vertical_alignment=ft.CrossAxisAlignment.START),
                        padding=ft.Padding(10, 10, 10, 10), border_radius=10, on_click=toggle,
                        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"))


class PluginsView:
    def __init__(self, app):
        self.app = app
        self.notice = ft.Container()
        self.column = ft.Column(spacing=t.GAP, width=None if t.compact else 760, expand=t.compact)
        self.zone = ft.Container()
        self.scroll = ft.ListView([ft.Row([self.column], alignment=ft.MainAxisAlignment.CENTER)],
                                  padding=ft.Padding(4, 8, 4, 24), expand=True)
        self.control = drop.target(ft.Container(t.fade(self.scroll), expand=True), self._dropped,
                                   glow=lambda: self.zone)
        self.downloading = ""      # the plugin whose package is downloading
        self.tab = "installed"
        self.source_field = t.field(hint=tr('plugins.source_hint', 'OWNER/REPO or https://...'), mono=True,
                                    expand=True, on_submit=lambda e: self._add_source())
        self.adding = False
        app.plugin_update_listeners.append(lambda: self.render(update=self.column.page is not None))
        self.render()

    def enter(self, **_) -> None:
        self.render()

    def leave(self) -> None:
        self.notice.content = None

    # Rendering

    def render(self, update: bool = False) -> None:
        found = plugins.discover()
        loaded = {p.id: p for p in plugins.load()}
        rows = [self._row(p, loaded.get(p.id)) for p in found]
        header = ft.Container(ft.Row([
            t.pixel_icon("plug", size=24, color=t.RED),
            t.text(tr('plugins.plugins_9514b7', 'Plugins'), 22, weight=ft.FontWeight.W_600, expand=True),
            *([] if t.compact else [t.secondary_button(tr('plugins.how_to_make_one_ca2bd2', 'How to make one'),
                                                       lambda e: self.app.navigate("docs", doc="plugins.md"), "book-open")]),
            t.button(tr('plugins.add_a_plugin_98bbc5', 'Add a plugin'), self._pick, "plus"),
        ], spacing=10), padding=ft.Padding(4, 12, 0, 0))
        self.zone = self._zone(compact=bool(rows))
        listings = self._listings()
        available = sum(len(s.entries) for s in listings)
        tabs = t.segmented([
            ("installed", tr('plugins.tab_installed', 'Installed · {value0}', value0=len(rows)), "plug"),
            ("browse", tr('plugins.tab_browse', 'Browse · {value0}', value0=available), "package"),
            ("sources", tr('plugins.tab_sources', 'Sources · {value0}', value0=len(listings)), "globe"),
        ], self.tab, self._tab, wrap=True)
        tabs = ft.Container(tabs, padding=4, border_radius=999, bgcolor=ft.Colors.with_opacity(0.05, "#FFFFFF"))
        if self.tab == "browse":
            self.column.controls = [header, ft.Row([tabs]), self.notice, *self._browse(listings)]
        elif self.tab == "sources":
            self.column.controls = [header, ft.Row([tabs]), self.notice, *self._sources(listings)]
        if self.tab != "installed":
            if update:
                self.column.update()
            return
        installed = t.section(
            tr('plugins.installed_b9a401', 'Installed · {value0}', value0=len(rows)) if rows else tr('plugins.installed_f8b32f', 'Installed'),
            ft.Column([*rows, t.text(tr('plugins.this_pokeldn_runs_plugin_api_4e68e6', 'This pokeldn runs plugin API {value0}.{value1}.', value0=plugins.API_VERSION, value1=plugins.API_LEVEL),
                                     12, t.FAINT)], spacing=8) if rows else None,
            trailing=ft.Row([
                t.icon_button("refresh", self._refresh, tr('plugins.look_for_changes_and_updates_0fa28f', 'Look for changes and updates')),
                t.icon_button("folder", self._open_folder, tr('plugins.open_the_plugins_folder_77e53c', 'Open the plugins folder')),
            ], spacing=0))
        self.column.controls = [header, ft.Row([tabs]), self.notice, self.zone, *([installed] if rows else []),
                                *self._radio_card()]
        if update:
            self.column.update()

    def _zone(self, compact: bool) -> ft.Container:
        title = (tr('plugins.drop_a_pokeplugin_file_here_dabba6', 'Drop a .pokeplugin file here') if drop.AVAILABLE else tr('plugins.add_a_pokeplugin_file_42b275', 'Add a .pokeplugin file'))
        lead = t.tinted(t.pixel_icon("archive", size=24 if compact else 48), t.BRAND_BLUE)
        body = [t.text(title, 15 if not compact else 13, weight=ft.FontWeight.W_600),
                t.text(tr('plugins.plugins_add_tools_and_radios_made_by_other_people_you_s_580f52', 'Plugins add tools and radios made by other people. You see what a plugin is and accept its risks before anything is installed.'), 12, t.MUTED,
                       text_align=None if compact else ft.TextAlign.CENTER)]
        choose = t.secondary_button(tr('plugins.choose_a_file_3e10c3', 'Choose a file'), self._pick, "folder")
        if compact:
            content = ft.Row([lead, ft.Column(body, spacing=2, expand=True), choose], spacing=14)
            padding = ft.Padding(18, 14, 14, 14)
        else:
            content = ft.Column([lead, *body, ft.Container(height=4), choose], spacing=8,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            padding = ft.Padding(32, 36, 32, 32)
        return ft.Container(content, padding=padding, border_radius=16, bgcolor=t.CARD,
                            border=ft.Border.all(1.5, ft.Colors.with_opacity(0.12, "#FFFFFF")),
                            on_click=self._pick if not compact else None)

    def _row(self, plugin: plugins.Plugin, state: plugins.Plugin | None) -> ft.Control:
        s = self.app.settings
        local = plugin.folder is not None and plugin.folder.parent == plugins.folder()
        forced = plugins.named(plugin)
        on = state is not None
        meta = " · ".join(x for x in (tr('plugins.version_label', 'Version {value0}', value0=plugin.version) if plugin.version else "",
                                      tr('plugins.author_label', 'by {value0}', value0=plugin.author) if plugin.author else "",
                                      f"plugin API {plugins.api_text(plugin.api)}") if x)
        lines: list[ft.Control] = [
            ft.Row([t.text(plugin.name, 14, weight=ft.FontWeight.W_600), self._status(plugin, state)],
                   spacing=10, wrap=True),
        ]
        if meta:
            lines.append(t.text(meta, 12, t.FAINT))
        if plugin.description:
            lines.append(t.text(plugin.description, 12, t.MUTED))
        if state is not None and state.error:
            lines.append(ft.Container(t.text(state.error, 12, t.SOFT, selectable=True, font_family=t.MONO),
                                      padding=10, border_radius=8,
                                      bgcolor=ft.Colors.with_opacity(0.08, t.RED)))
        elif on:
            chips = self._adds(state)
            if chips:
                lines.append(ft.Row(chips, spacing=6, run_spacing=6, wrap=True))
        elif plugin.error:
            lines.append(t.badge(translate(plugin.error), t.RED, "warning-diamond"))
        level, message = plugins.compatibility(plugin.api)
        if level == "deprecated":
            lines.append(t.badge(translate(message), t.AMBER, "warning-diamond"))
        available = self.app.plugin_updates.get(plugin.id)
        if available is not None and local:
            busy = self.downloading == plugin.id
            lines.append(ft.Row([
                t.chip(tr('plugins.version_is_out_5d779b', 'Version {value0} is out', value0=available.version), "upload", t.GREEN),
                t.button(tr('plugins.downloading_37b345', 'Downloading') if busy else tr('plugins.update_to_e0a321', 'Update to {value0}', value0=available.version),
                         lambda e, a=available, p=plugin: self._download(a, p.name), "download", color=t.GREEN,
                         disabled=bool(self.downloading)),
            ], spacing=8, wrap=True))
        origin = store.origin(plugin) if local else ""
        if origin:
            lines.append(t.badge(tr('plugins.from_source', 'From {value0}', value0=sources.label(
                self._listing(origin))), t.FAINT, "globe"))
        if forced:
            lines.append(t.badge(tr('plugins.loaded_from_pokeldn_plugins_it_is_on_while_that_variabl_36c4f8', 'Loaded from POKELDN_PLUGINS: it is on while that variable names it.'), t.FAINT))
        elif plugin.entry_point is not None:
            lines.append(t.badge(tr('plugins.installed_as_a_python_package_9bf470', 'Installed as a Python package.'), t.FAINT))

        def item(label, icon, action, color=t.MUTED):
            return ft.PopupMenuItem(ft.Row([t.pixel_icon(icon, color=color), t.text(label, 13)], spacing=10),
                                    on_click=action, height=40)
        menu_items = []
        if on and state.loaded and (first := self._first_tool(state)):
            menu_items.append(item(tr('plugins.open_its_tools_e5ec29', 'Open its tools'), "gamepad", lambda e, k=first: self._open_tool(*k)))
        if local:
            menu_items += [item(tr('plugins.update_from_a_file_ed27b3', 'Update from a file'), "upload", lambda e, p=plugin: self.app.page.run_task(
                self._pick_update, p)),
                           item(tr('plugins.show_in_folder_da4787', 'Show in folder'), "folder", lambda e, p=plugin: open_folder(str(p.folder)))]
        if plugin.homepage:
            menu_items.append(item(tr('plugins.visit_its_page_ffc99d', 'Visit its page'), "external-link",
                                   lambda e, u=plugin.homepage: self.app.page.run_task(self.app.open_url, u)))
        if local:
            menu_items.append(item(tr('plugins.remove_c3812f', 'Remove'), "trash", lambda e, p=plugin: self._confirm_remove(p), t.RED))
        menu = ft.PopupMenuButton(
            content=ft.Container(t.pixel_icon("more-vertical", color=t.MUTED), width=32, height=32,
                                 alignment=ft.Alignment.CENTER),
            tooltip=tr('plugins.more_d47d7c', 'More'), bgcolor=t.PANEL, menu_position=ft.PopupMenuPosition.UNDER,
            items=menu_items) if menu_items else ft.Container(width=32)
        toggle = t.switch(plugin.id in s.plugins or forced, lambda e, p=plugin: self._toggle(p, e.control.value))
        toggle.disabled = forced or bool(plugin.error) or \
            plugins.compatibility(plugin.api)[0] in ("newer", "older")
        toggle.tooltip = tr('plugins.turn_on_5a1f09', 'Turn on') if not on else tr('plugins.turn_off_06f0e2', 'Turn off')
        return t.surface(ft.Container(ft.Row([
            plugin_icon(plugin.icon),
            ft.Column(lines, spacing=4, expand=True),
            ft.Row([toggle, menu], spacing=2),
        ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START), padding=ft.Padding(16, 14, 8, 14)))

    def _status(self, plugin: plugins.Plugin, state: plugins.Plugin | None) -> ft.Control:
        if plugins.compatibility(plugin.api)[0] in ("newer", "older"):
            return t.chip(tr('plugins.not_compatible_8b6f0c', 'Not compatible'), "warning-diamond", t.RED)
        if plugin.error or (state is not None and state.error):
            return t.chip(tr('plugins.failed_031a8f', 'Failed'), "warning-diamond", t.RED)
        if state is not None:
            return t.chip(tr('plugins.on_130011', 'On'), "check", t.GREEN)
        if plugin.folder is not None and plugin.folder.parent == plugins.folder() and not store.consented(plugin):
            return t.chip(tr('plugins.added_by_hand_cd55f7', 'Added by hand'), "warning-diamond", t.AMBER)
        return t.chip(tr('plugins.off_ca7981', 'Off'), None, t.FAINT)

    def _adds(self, state: plugins.Plugin) -> list[ft.Control]:
        names = {g.key: g.name for g in plugins.games()}
        chips = [t.chip(tr('plugins.tool_d0d814', '{value0} · {value1} tool{value2}', value0=g.name, value1=len(g.tools), value2=tr('plugins.plural_suffix', 's') * (len(g.tools) != 1)), "gamepad", t.BLUE)
                 for g in state.games]
        chips += [t.chip(tr('plugins.in_8e5a60', '{value0} in {value1}', value0=tool.name, value1=names.get(game, game)), "arrows-horizontal", t.BLUE)
                  for game, tool in state.tools]
        chips += [t.chip(tr('plugins.radio_78fa73', 'Radio: {value0}', value0=plugins.radio(r).label), "cpu", t.AMBER) for r in state.radios]
        return chips

    def _radio_card(self) -> list[ft.Control]:
        s = self.app.settings
        choices = [("", tr('plugins.the_board_default_e0fd57', 'The board (default)'))] + [(r.scheme, tr('plugins.ldnrs_radio', 'USB Wi-Fi (Windows, ldnrs)') if r.scheme == 'ldnrs' else r.label) for r in radios.choices()]
        if s.radio and s.radio not in {c[0] for c in choices}:
            choices.append((s.radio, tr('plugins.its_plugin_is_off_dc8701', '{value0} (its plugin is off)', value0=s.radio)))
        if len(choices) == 1:
            return []
        help_controls = [t.text(tr('plugins.the_games_page_shows_the_radio_in_use_before_you_start_87e986', 'The Games page shows the radio in use before you start.'), 12, t.MUTED)]
        if any(key == "ldnrs" for key, label in choices):
            help_controls += [
                t.text(tr('plugins.for_usb_wi_fi_on_windows_install_ldnrs_0_0_3_complete_i_a1a117', "For USB Wi-Fi on Windows, install ldnrs 0.0.3, complete its adapter wizard and keep its daemon running. Its setup replaces the adapter's Wi-Fi driver with WinUSB; restore the original driver in Device Manager to use that adapter for ordinary Wi-Fi again."), 12, t.MUTED),
                t.link_button(tr('plugins.ldnrs_setup_and_download_ba2dbf', 'ldnrs setup and download'), lambda e: self.app.page.run_task(
                    self.app.open_url, "https://github.com/unlimitedcoder2/ldnrs/releases/tag/0.0.3"))]
        return [t.section(tr('plugins.radio_2a7dfe', 'Radio'), t.card(
            tr('plugins.what_carries_the_wireless_messages_dad79a', 'What carries the wireless messages'),
            ft.Column([ft.Row([t.dropdown(choices, s.radio, on_select=lambda e: self._set_radio(e.control.value or ""))]),
                       *help_controls], spacing=8, tight=True)))]

    def _first_tool(self, state: plugins.Plugin):
        for game in state.games:
            if game.tools:
                return game.key, game.tools[0].key
        return (state.tools[0][0], state.tools[0][1].key) if state.tools else None

    # Sources

    def _tab(self, key: str) -> None:
        self.tab = key
        self.render(update=True)

    def _listings(self) -> list:
        """Every followed source, as last read in this run or from the cache."""
        read = {s.url: s for s in getattr(self.app, "plugin_sources", [])}
        return [read.get(url) or sources.cached(url) for url in sources.followed()]

    def _listing(self, url: str):
        return next((s for s in getattr(self.app, "plugin_sources", []) if s.url == url), None) or sources.cached(url)

    def _browse(self, listings: list) -> list[ft.Control]:
        found = {p.id: p for p in plugins.discover()
                 if p.folder is not None and p.folder.parent == plugins.folder()}
        out = []
        for source in listings:
            rows: list[ft.Control] = [self._entry_row(source, e, found.get(e.id)) for e in source.entries]
            if source.error:
                rows.insert(0, t.badge(translate(source.error), t.AMBER, "warning-diamond"))
            if not source.entries and not source.error:
                rows.append(t.text(tr('plugins.source_unread', 'Not read yet. Press refresh to read it.')
                                   if not source.fetched else tr('plugins.source_empty', 'This source lists no plugins.'),
                                   12, t.FAINT))
            out.append(t.section(sources.label(source), ft.Column(rows, spacing=8), trailing=t.icon_button(
                "refresh", self._refresh, tr('plugins.read_sources_again', 'Read the sources again'))))
        return out

    def _entry_row(self, source, entry, current: plugins.Plugin | None) -> ft.Control:
        state = sources.state(entry, current)
        meta = " · ".join(x for x in (tr('plugins.version_label', 'Version {value0}', value0=entry.version), tr('plugins.author_label', 'by {value0}', value0=entry.author) if entry.author else "",
                                      store.size_text(entry.size) if entry.size else "") if x)
        lines: list[ft.Control] = [t.text(entry.name, 14, weight=ft.FontWeight.W_600), t.text(meta, 12, t.FAINT)]
        if entry.description:
            lines.append(t.text(entry.description, 12, t.MUTED))
        busy = self.downloading == entry.id

        def available():
            from pokeldn.app.plugin_updates import Available
            return Available(entry.id, entry.version, entry.download, entry.homepage or source.homepage,
                             entry.sha256, source.url)
        actions: list[ft.Control] = []
        if state == "incompatible":
            lines.append(t.badge(translate(plugins.compatibility(entry.api)[1]), t.RED, "warning-diamond"))
        elif state == "install":
            actions.append(t.button(tr('plugins.downloading_37b345', 'Downloading') if busy else tr('plugins.install_569ca4', 'Install'),
                                    lambda e: self._download(available(), entry.name), "download",
                                    disabled=bool(self.downloading)))
        elif state == "update":
            actions.append(t.button(tr('plugins.downloading_37b345', 'Downloading') if busy else tr('plugins.update_to_e0a321', 'Update to {value0}', value0=entry.version),
                                    lambda e: self._download(available(), entry.name), "download", color=t.GREEN,
                                    disabled=bool(self.downloading)))
        else:
            actions.append(t.chip(tr('plugins.installed_f8b32f', 'Installed') if state == "installed" else
                                  tr('plugins.newer_installed', 'Version {value0} installed', value0=current.version),
                                  "check", t.GREEN))
        if current is not None:
            actions.append(t.icon_button("trash", lambda e, p=current: self._confirm_remove(p),
                                         tr('plugins.remove_c3812f', 'Remove'), color=t.RED))
        if entry.homepage:
            actions.append(t.icon_button("external-link", lambda e: self.app.page.run_task(self.app.open_url, entry.homepage),
                                         tr('plugins.visit_its_page_ffc99d', 'Visit its page')))
        icon = ft.Container(ft.Image(src=entry.icon, width=48, height=48, fit=ft.BoxFit.CONTAIN,
                                     error_content=plugin_icon()), width=48, height=48, border_radius=48 * 0.22,
                            clip_behavior=ft.ClipBehavior.ANTI_ALIAS) if entry.icon else plugin_icon()
        return t.surface(ft.Container(ft.Row([
            icon, ft.Column(lines, spacing=4, expand=True),
            ft.Row(actions, spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START), padding=ft.Padding(16, 14, 12, 14)))

    def _sources(self, listings: list) -> list[ft.Control]:
        add = t.card(tr('plugins.add_a_source', 'Add a source'), ft.Row([
            self.source_field,
            t.button(tr('plugins.adding_source', 'Reading') if self.adding else tr('plugins.add_5e2ed1', 'Add'),
                     lambda e: self._add_source(), "plus", disabled=self.adding),
        ], spacing=8), tr('plugins.source_explained', 'A source is a list of plugins someone publishes. Its plugins appear '
                          'under Browse, and their updates on their cards. Following a source means trusting its '
                          'publisher; every install still shows the risk screen.'))
        rows = []
        for source in listings:
            facts = [tr('plugins.source_count', '{value0} plugin{value1}', value0=len(source.entries),
                        value1=tr('plugins.plural_suffix', 's') * (len(source.entries) != 1))]
            if source.fetched:
                facts.append(tr('plugins.source_read', 'read {value0}', value0=time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(source.fetched))))
            lines: list[ft.Control] = [
                ft.Row([t.text(sources.label(source), 14, weight=ft.FontWeight.W_600),
                        *([t.chip(tr('plugins.built_in', 'Built in'), "check", t.BLUE)] if source.built_in else [])],
                       spacing=10, wrap=True),
                t.text(source.url, 11, t.FAINT, selectable=True, font_family=t.MONO),
                t.text(" · ".join(facts), 12, t.MUTED)]
            if source.error:
                lines.append(t.badge(translate(source.error), t.AMBER, "warning-diamond"))
            actions = []
            if source.homepage:
                actions.append(t.icon_button("external-link", lambda e, u=source.homepage: self.app.page.run_task(
                    self.app.open_url, u), tr('plugins.visit_its_page_ffc99d', 'Visit its page')))
            if not source.built_in:
                actions.append(t.icon_button("trash", lambda e, s=source: self._remove_source(s),
                                             tr('plugins.remove_source', 'Stop following'), color=t.RED))
            rows.append(t.surface(ft.Container(ft.Row([
                t.tinted(t.pixel_icon("globe", size=24), t.BRAND_BLUE),
                ft.Column(lines, spacing=4, expand=True), ft.Row(actions, spacing=0),
            ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START), padding=ft.Padding(16, 14, 8, 14))))
        return [add, t.section(tr('plugins.followed_sources', 'Followed'), ft.Column(rows, spacing=8), trailing=t.icon_button(
            "refresh", self._refresh, tr('plugins.read_sources_again', 'Read the sources again')))]

    def _add_source(self) -> None:
        text = (self.source_field.value or "").strip()
        if self.adding or not text:
            return
        self.adding = True
        self.render(update=True)

        def work():
            try:
                source, error = sources.add(text), ""
            except sources.SourceError as failure:
                source, error = None, str(failure)
            self.app.ui(lambda: done(source, error))

        def done(source, error):
            self.adding = False
            if source is None:
                self.render(update=True)
                self.error_dialog(tr('plugins.source_not_added', 'The source was not added'), error)
                return
            self.source_field.value = ""
            self.app.plugin_sources = [*[s for s in self.app.plugin_sources if s.url != source.url], source]
            self.say(tr('plugins.source_added', '{value0} added: {value1} plugin{value2} under Browse.',
                        value0=sources.label(source), value1=len(source.entries),
                        value2=tr('plugins.plural_suffix', 's') * (len(source.entries) != 1)), t.BLUE, "globe")
            self.app.check_plugin_updates()
            self.render(update=True)

        threading.Thread(target=work, daemon=True).start()

    def _remove_source(self, source) -> None:
        def done(e):
            self.app.page.pop_dialog()
            try:
                sources.remove(source.url)
            except sources.SourceError as error:
                self.error_dialog(tr('plugins.source_not_removed', 'The source was not removed'), str(error))
                return
            self.app.plugin_sources = [s for s in self.app.plugin_sources if s.url != source.url]
            self.say(tr('plugins.source_removed', '{value0} removed.', value0=sources.label(source)), t.MUTED, "trash")
            self.render(update=True)

        self.app.page.show_dialog(t.dialog(
            title=ft.Row([t.pixel_icon("globe", size=24, color=t.RED),
                          t.text(tr('plugins.remove_source_q', 'Stop following {value0}?', value0=sources.label(source)), 18, expand=True)],
                         spacing=12),
            content=t.text(tr('plugins.remove_source_body', 'Its plugins leave Browse. The ones you installed from it stay '
                              'installed, and no longer get updates from it.'), 13, t.MUTED, width=420),
            actions=[t.secondary_button(tr('plugins.cancel_19766e', 'Cancel'), lambda e: self.app.page.pop_dialog()),
                     t.button(tr('plugins.remove_c3812f', 'Remove'), done, "trash", color=t.RED)]))

    # Actions

    def say(self, text: str, color: str = t.GREEN, icon: str = "check", action: tuple | None = None) -> None:
        row = [t.pixel_icon(icon, color=color), t.text(text, 13, expand=True)]
        if action:
            row.append(t.link_button(*action))
        row.append(t.icon_button("close", self._clear_notice, tr('plugins.dismiss_48845b', 'Dismiss')))
        self.notice.content = ft.Container(ft.Row(row, spacing=10), padding=ft.Padding(14, 6, 6, 6),
                                           border_radius=12, bgcolor=ft.Colors.with_opacity(0.1, color))

    def _clear_notice(self, e=None) -> None:
        self.notice.content = None
        self.notice.update()

    def _reload(self, message: str = "") -> None:
        plugins.reload()
        s = self.app.settings
        if s.radio and radios.radio(s.radio) is None:
            s.radio = ""
            s.save()
            message = (message + " " if message else "") + tr('plugins.the_radio_is_back_to_the_board_01004b', 'The radio is back to the board.')
        if message:
            self.say(message, t.MUTED, "refresh")
        self.render(update=True)

    def _refresh(self, e=None) -> None:
        self._reload(tr('plugins.plugins_reloaded_looking_for_updates_ad41be', 'Plugins reloaded. Looking for updates.'))
        self.app.check_plugin_updates()

    def _download(self, available, name: str) -> None:
        from pokeldn.app import plugin_updates
        self.downloading = available.plugin
        self.render(update=True)

        def work():
            try:
                path, error = plugin_updates.download(available, SESSION / "plugin-download"), ""
            except OSError as failure:
                path, error = None, str(failure)
            self.app.ui(lambda: done(path, error))

        def done(path, error):
            self.downloading = ""
            self.render(update=True)
            if path is None:
                self.error_dialog(tr('plugins.did_not_download_31974e', '{value0} {value1} did not download', value0=name, value1=available.version), error)
            else:
                self.open_file(str(path), expected=available.plugin, origin=available.source, name=name)

        threading.Thread(target=work, daemon=True).start()

    def _open_folder(self, e) -> None:
        plugins.folder().mkdir(parents=True, exist_ok=True)
        open_folder(str(plugins.folder()))

    def _open_tool(self, game: str, tool: str) -> None:
        self.app.navigate("games", game=game, tool=tool)

    def _set_radio(self, scheme: str) -> None:
        self.app.settings.radio = scheme
        self.app.settings.save()
        radio = radios.radio(scheme)
        label = tr('plugins.ldnrs_radio', 'USB Wi-Fi (Windows, ldnrs)') if scheme == 'ldnrs' else radio.label if radio else ''
        self.say(tr('plugins.sessions_use_radio', 'Sessions now use {name}.', name=label) if radio else tr('plugins.sessions_use_board', 'Sessions now use the board.'), t.BLUE, "cpu")
        self.render(update=True)

    def _toggle(self, plugin: plugins.Plugin, value: bool) -> None:
        if value and plugin.folder is not None and not store.consented(plugin):
            try:
                package = store.describe(plugin)
            except (OSError, store.PackageError) as error:
                self.error_dialog(tr('plugins.cannot_be_turned_on_ec6344', '{value0} cannot be turned on', value0=plugin.name), str(error))
                self.render(update=True)
                return
            self.consent(package, "enable", plugin)
            self.render(update=True)     # the switch stays off until the user accepts
            return
        self._set_enabled(plugin.id, value)
        state = {p.id: p for p in plugins.load()}.get(plugin.id)
        if value and state is not None and state.error:
            self.say(tr('plugins.load_failed', '{name} failed to load. Its error is on its card.', name=plugin.name), t.RED, "warning-diamond")
        elif value:
            self.say(tr('plugins.turned_on', '{name} is on.', name=plugin.name), action=self._tools_action(plugin.id))
        else:
            self.say(tr('plugins.turned_off', '{name} is off. Its tools are hidden until you turn it on again.', name=plugin.name), t.MUTED, "check")
        self.render(update=True)

    def _set_enabled(self, plugin_id: str, value: bool) -> None:
        s = self.app.settings
        s.plugins = [i for i in s.plugins if i != plugin_id] + ([plugin_id] if value else [])
        s.save()
        plugins.reload()
        if s.radio and radios.radio(s.radio) is None:
            s.radio = ""
            s.save()

    def _tools_action(self, plugin_id: str):
        state = {p.id: p for p in plugins.load()}.get(plugin_id)
        first = self._first_tool(state) if state is not None and state.loaded else None
        return (tr('plugins.open_its_tools_e5ec29', 'Open its tools'), lambda e, k=first: self._open_tool(*k)) if first else None

    # Adding a package

    def _dropped(self, paths: list[str]) -> None:
        wanted = [p for p in paths if drop.suffix(p) == store.EXTENSION]
        if not wanted:
            self.error_dialog(tr('plugins.not_a_plugin_559bfb', 'Not a plugin'), tr('plugins.drop_a_file_ending_in_pokeplugin_ca2a6f', 'Drop a file ending in .pokeplugin.'))
            return
        self.open_file(wanted[0])

    async def _pick(self, e=None) -> None:
        files = await self.app.picker.pick_files(dialog_title=tr('plugins.choose_a_plugin_378868', 'Choose a plugin'), allowed_extensions=[store.EXTENSION],
                                                 file_type=ft.FilePickerFileType.CUSTOM)
        if files and files[0].path:
            self.open_file(files[0].path)

    async def _pick_update(self, plugin: plugins.Plugin) -> None:
        files = await self.app.picker.pick_files(dialog_title=tr('plugins.update_d3aff3', 'Update {value0}', value0=plugin.name),
                                                 allowed_extensions=[store.EXTENSION],
                                                 file_type=ft.FilePickerFileType.CUSTOM)
        if files and files[0].path:
            self.open_file(files[0].path, expected=plugin.id, name=plugin.name)

    def open_file(self, path: str, expected: str = "", origin: str = "", name: str = "") -> None:
        """Reads a package and shows what it is with its risks; nothing is installed before the user accepts.
        `expected` is the plugin id the file must carry; `origin` the source listing it came from."""
        try:
            package = store.read(path)
        except store.PackageError as error:
            self.error_dialog(tr('plugins.cannot_be_installed_be6812', '{value0} cannot be installed', value0=os.path.basename(path)), str(error))
            return
        if expected and package.id != expected:
            self.error_dialog(tr('plugins.a_different_plugin_a99fbe', 'A different plugin'), tr('plugins.is_not_an_update_of_1b4f96', '{value0} is {value1}, not an update of {value2}.', value0=os.path.basename(path), value1=package.name, value2=name or expected))
            return
        current = store.installed(package.id)
        self.consent(package, store.compare(package, current), current, origin)

    def error_dialog(self, title: str, message: str) -> None:
        self.app.page.show_dialog(t.dialog(
            title=ft.Row([t.pixel_icon("warning-diamond", size=24, color=t.RED), t.text(title, 18, expand=True)],
                         spacing=10),
            content=t.text(translate(message), 13, t.MUTED, width=420, selectable=True),
            actions=[t.button(tr('plugins.ok_565339', 'OK'), lambda e: self.app.page.pop_dialog())]))

    def consent(self, package: store.Package, action: str, current: plugins.Plugin | None, origin: str = "") -> None:
        """The risk screen every install, update and first turn-on goes through."""
        trust = store.trust(package)
        stranger = trust in ("changed", "dropped")     # not the author of the copy seen before
        state = {"accepted": False, "enable": True, "stranger": not stranger}
        go = t.button(tr('plugins.turn_on_5a1f09', 'Turn on') if action == "enable" else ACTIONS[action], None,
                      "check", disabled=True, color=t.RED if stranger else t.BLUE)

        def ready() -> None:
            go.disabled = not (state["accepted"] and state["stranger"])
            go.update()

        def accepted(value: bool) -> None:
            state["accepted"] = value
            ready()

        def stranger_ok(value: bool) -> None:
            state["stranger"] = value
            ready()

        def enable(e) -> None:
            state["enable"] = bool(e.control.value)

        def close(e=None) -> None:
            self.app.page.pop_dialog()

        def confirm(e) -> None:
            if not (state["accepted"] and state["stranger"]):
                return
            close()
            self._accepted(package, action, current, state["enable"], origin)

        go.on_click = confirm
        meta = " · ".join(x for x in (tr('plugins.version_label', 'Version {value0}', value0=package.version) if package.version else "",
                                      tr('plugins.author_label', 'by {value0}', value0=package.author) if package.author else tr('plugins.by_an_unnamed_author_da6876', 'by an unnamed author')) if x)
        lines: list[ft.Control] = [
            ft.Row([
                plugin_icon(package.icon or (current.icon if current else ""), 56),
                ft.Column([t.text(package.name, 20, weight=ft.FontWeight.W_600),
                           t.text(meta, 12, t.MUTED)], spacing=2, expand=True),
                t.icon_button("close", close, tr('plugins.cancel_19766e', 'Cancel')),
            ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START),
        ]
        if package.description:
            lines.append(t.text(package.description, 13, t.SOFT))
        version_note = {
            "update": (f"Updates {current.name if current else ''} from {current.version if current else '?'} "
                       f"to {package.version}. What it saved is kept.", t.BLUE, "upload"),
            "reinstall": (f"Version {package.version} is already installed; this replaces its files.", t.MUTED,
                          "refresh"),
            "downgrade": (f"Installs {package.version} over the newer {current.version if current else '?'}.",
                          t.AMBER, "warning-diamond"),
            "enable": (tr('plugins.this_plugin_was_copied_into_the_plugins_folder_by_hand__25f250', 'This plugin was copied into the plugins folder by hand and was never checked in the app.'),
                       t.AMBER, "warning-diamond"),
        }.get(action)
        if version_note:
            lines.append(t.badge(*version_note))
        level, message = plugins.compatibility(package.api)
        if level == "deprecated":
            lines.append(t.badge(translate(message), t.AMBER, "warning-diamond"))
        if origin:
            lines.append(t.badge(tr('plugins.listed_by', 'Listed by {value0}; the file matches its listing.',
                                    value0=sources.label(self._listing(origin))), t.FAINT, "globe"))
        if package.library:
            lines.append(t.badge(tr('plugins.keeps_files_in', 'Keeps its files in {value0}. Removing the plugin leaves them there.',
                                    value0=library.shown(plugins.library_path(package.library))), t.BLUE, "folder"))
        if package.source:
            lines.append(t.badge(tr('plugins.files_886156', '{value0} · {value1} files · {value2}', value0=os.path.basename(package.source), value1=package.files, value2=store.size_text(package.size)), t.FAINT, "archive"))
        lines.append(self._signature(package, trust))
        lines.append(self._findings(package.findings))
        lines.append(ft.Container(ft.Row([
            t.pixel_icon("warning-diamond", size=24, color=t.RED),
            ft.Column([t.text(tr('plugins.plugins_run_with_full_access_c09f83', 'Plugins run with full access'), 14, weight=ft.FontWeight.W_600),
                       *[ft.Row([t.text("·", 13, t.RED), t.text(r, 12, t.SOFT, expand=True)], spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.START) for r in RISKS]],
                      spacing=6, expand=True),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            padding=16, border_radius=14, bgcolor=ft.Colors.with_opacity(0.08, t.RED),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, t.RED))))
        if stranger:
            lines.append(checkbox(tr('plugins.i_know_this_file_does_not_come_from_the_author_of_the_v_0fcdfc', 'I know this file does not come from the author of the version I had, and I install it anyway.'), False, stranger_ok))
        lines.append(checkbox(tr('plugins.i_understand_these_risks_and_i_trust_the_author_of_this_a347eb', 'I understand these risks, and I trust the author of this plugin.'), False, accepted))
        if action != "enable":
            lines.append(ft.Row([t.text(tr('plugins.turn_it_on_after_installing_3346b3', 'Turn it on after installing'), 13, expand=True),
                                 t.switch(True, enable)]))
        self.app.page.show_dialog(t.dialog(
            modal=True, content_padding=0, actions_padding=0, inset_padding=32, scrollable=True,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS, semantics_label=tr('plugins.install_fa4031', 'Install {value0}', value0=package.name),
            content=ft.Container(ft.Column([
                ft.Container(ft.Column(lines, spacing=12, tight=True), padding=ft.Padding(26, 22, 18, 6)),
                ft.Container(ft.Row([ft.Container(expand=True), t.secondary_button(tr('plugins.cancel_19766e', 'Cancel'), close), go],
                                    spacing=8), padding=ft.Padding(26, 12, 22, 22)),
            ], spacing=0, tight=True), width=540, border_radius=20)))

    @staticmethod
    def _signature(package: store.Package, trust: str) -> ft.Control:
        """Who signed the file, against the author of the copy this app saw before."""
        key = tr('plugins.key_6574f7', 'key {value0}', value0=store.fingerprint(package.key)) if package.key else ""
        title, text, color, icon = {
            "same": (tr('plugins.signed_by_the_same_author_c03314', 'Signed by the same author'), tr('plugins.the_same_signed_the_version_installed_before_b19d2b', 'The same {value0} signed the version installed before.', value0=key),
                     t.GREEN, "shield"),
            "new": (tr('plugins.signed_by_its_author_332f56', 'Signed by its author'), tr('plugins.signed_with_if_the_author_publishes_their_key_compare_i_e0ac4c', 'Signed with {value0}. If the author publishes their key, compare it. Every update must carry the same key.', value0=key), t.BLUE, "key"),
            "unsigned": (tr('plugins.not_signed_c0f06f', 'Not signed'), tr('plugins.nothing_proves_who_made_this_file_or_that_it_was_not_ch_08a343', 'Nothing proves who made this file or that it was not changed since.'),
                         t.AMBER, "warning-diamond"),
            "changed": (tr('plugins.signed_by_someone_else_9717d0', 'Signed by someone else'), tr('plugins.signed_with_not_the_key_of_the_author_of_the_version_in_8bc22d', 'Signed with {value0}, not the key of the author of the version installed before. Someone else may have made this file.', value0=key), t.RED, "warning-diamond"),
            "dropped": (tr('plugins.no_longer_signed_699438', 'No longer signed'), tr('plugins.the_version_installed_before_was_signed_by_its_author_t_934b9e', 'The version installed before was signed by its author; this file is not. Someone else may have made it.'), t.RED, "warning-diamond"),
        }[trust]
        return ft.Container(ft.Row([t.pixel_icon(icon, size=24, color=color), ft.Column([
            t.text(title, 14, weight=ft.FontWeight.W_600), t.text(text, 12, t.SOFT, selectable=True)],
            spacing=4, expand=True)], spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
            padding=16, border_radius=14, bgcolor=ft.Colors.with_opacity(0.06, color),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, color)))

    @staticmethod
    def _findings(findings: list[str]) -> ft.Control:
        """What a reading of its code found; it informs, it cannot clear a plugin."""
        if findings:
            body = [t.text(tr('plugins.what_its_code_does_4e3d2b', 'What its code does'), 14, weight=ft.FontWeight.W_600),
                    *[ft.Row([t.text("·", 13, t.AMBER), t.text(translate(f), 12, t.SOFT, expand=True)], spacing=8,
                             vertical_alignment=ft.CrossAxisAlignment.START) for f in findings]]
            color, icon = t.AMBER, "search"
        else:
            body = [t.text(tr('plugins.what_its_code_does_4e3d2b', 'What its code does'), 14, weight=ft.FontWeight.W_600),
                    t.text(tr('plugins.no_network_program_deletion_or_hidden_code_found_in_its_d7aec0', 'No network, program, deletion or hidden code found in its files. A reading of the code cannot prove a plugin safe.'), 12, t.SOFT)]
            color, icon = t.BLUE, "search"
        return ft.Container(ft.Row([t.pixel_icon(icon, size=24, color=color), ft.Column(body, spacing=6, expand=True)],
                                   spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                            padding=16, border_radius=14, bgcolor=ft.Colors.with_opacity(0.06, color),
                            border=ft.Border.all(1, ft.Colors.with_opacity(0.25, color)))

    def _accepted(self, package: store.Package, action: str, current, enable: bool, origin: str = "") -> None:
        if action == "enable":
            store.accept(current, package.key)
            self._toggle(current, True)
            return
        try:
            store.install(package, origin)
        except (OSError, store.PackageError) as error:
            self.error_dialog(tr('plugins.was_not_installed_b59499', '{value0} was not installed', value0=package.name), str(error))
            return
        if package.source.startswith(str(SESSION / "plugin-download")):
            shutil.rmtree(SESSION / "plugin-download", ignore_errors=True)
        if self.app.plugin_updates.pop(package.id, None) is not None:
            self.app._plugin_updates_done(self.app.plugin_updates)
        if enable:
            self._set_enabled(package.id, True)
        else:
            plugins.reload()
        state = {p.id: p for p in plugins.load()}.get(package.id)
        done = {"install": tr('plugins.installed', 'installed'), "update": tr('plugins.updated_to_8ce2a6', 'updated to {value0}', value0=package.version),
                "reinstall": tr('plugins.reinstalled', 'reinstalled'), "downgrade": tr('plugins.now_at_715c26', 'now at {value0}', value0=package.version)}[action]
        if state is not None and state.error:
            self.say(tr('plugins.installed_load_failed', '{name} is {state} but failed to load. Its error is on its card.', name=package.name, state=done), t.RED,
                     "warning-diamond")
        elif enable:
            self.say(tr('plugins.installed_on', '{name} is {state} and on.', name=package.name, state=done), action=self._tools_action(package.id))
        else:
            self.say(tr('plugins.installed_off', '{name} is {state}. Turn it on when you want its tools.', name=package.name, state=done), t.MUTED)
        self.render(update=True)

    # Removing

    def _confirm_remove(self, plugin: plugins.Plugin) -> None:
        kept = plugins.data_folder(plugin.id).is_dir()
        state = {"data": False}

        def done(e):
            self.app.page.pop_dialog()
            try:
                store.remove(plugin.id, data=state["data"])
            except (OSError, store.PackageError) as error:
                self.error_dialog(tr('plugins.was_not_removed_90feb9', '{value0} was not removed', value0=plugin.name), str(error))
                return
            self._set_enabled(plugin.id, False)
            self.say(tr('plugins.removed', '{name} is removed.', name=plugin.name), t.MUTED, "trash")
            self.render(update=True)

        self.app.page.show_dialog(t.dialog(
            title=ft.Row([plugin_icon(plugin.icon, 32), t.text(tr('plugins.remove_bc43ab', 'Remove {value0}?', value0=plugin.name), 18, expand=True)],
                         spacing=12),
            content=ft.Column([
                t.text(tr('plugins.its_files_are_deleted_from_this_computer_and_its_tools__3d0fb7', 'Its files are deleted from this computer and its tools leave the Games page. A session it is running keeps going until it ends.'), 13, t.MUTED),
                *([t.badge(tr('plugins.library_stays', 'Its library stays: {value0}.',
                              value0=library.shown(plugins.library_path(plugin.library))), t.MUTED, "folder")]
                  if plugin.library else []),
                *([checkbox(tr('plugins.also_delete_what_it_saved_otherwise_installing_it_again_75d934', 'Also delete what it saved ({value0}); otherwise installing it again finds it.', value0=store.size_text(store.kept_data(plugin.id))), False,
                            lambda value: state.update(data=value))] if kept else []),
            ], spacing=12, tight=True, width=420),
            actions=[t.secondary_button(tr('plugins.cancel_19766e', 'Cancel'), lambda e: self.app.page.pop_dialog()),
                     t.button(tr('plugins.remove_c3812f', 'Remove'), done, "trash", color=t.RED)]))
