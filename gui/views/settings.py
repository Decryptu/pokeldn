import copy
import os
import threading

import flet as ft

from gui import theme as t
from gui.app import keys_found
from pokeldn import __version__, pokemon, plugins
from pokeldn.app.paths import SESSION
from pokeldn.app.sprites import CACHE
from pokeldn.app.settings import switch_ids_valid
from pokeldn.app import storage
from gui.views.widgets import PathField, open_folder
from pokeldn.app.i18n import t as tr

LANGUAGES = (("2", tr("settings.language_english", "English")),
             ("3", tr("settings.language_french", "French")),
             ("5", tr("settings.language_german", "German")),
             ("4", tr("settings.language_italian", "Italian")),
             ("7", tr("settings.language_spanish", "Spanish")),
             ("1", tr("settings.language_japanese", "Japanese")),
             ("8", tr("settings.language_korean", "Korean")),
             ("9", tr("settings.language_simplified_chinese", "Simplified Chinese")),
             ("10", tr("settings.language_traditional_chinese", "Traditional Chinese")))

LINKS = ((tr('settings.documentation_c20592', 'Documentation'), "https://decryptu.github.io/pokeldn/"),
         (tr('settings.github_f911e4', 'GitHub'), "https://github.com/Decryptu/pokeldn"),
         (tr('settings.discord_053bc6', 'Discord'), "https://discord.gg/PyvaVYnpXC"))


class SettingsView:
    def __init__(self, app):
        self.app = app
        self.keys_state = ft.Container()
        self.sprite_state = t.text("", 12, t.MUTED)
        self.update_state = t.text("", 12, t.MUTED)
        self.storage_state = t.text(tr('settings.checking_local_files_77c76c', 'Checking local files...'), 12, t.MUTED)
        self.storage_result = t.text("", 12, t.MUTED, visible=False)
        self.storage_inventory = storage.Inventory()
        self.storage_work = False
        self.clear_button = t.button(tr('settings.clear_local_files_2f0392', 'Clear local files'), self._clear_local, "folder", filled=False,
                                     disabled=True)
        self.shown = self.asked = False
        app.update_listeners.append(self._update_shown)
        self._update_text()
        self.show_advanced = False
        self.column = ft.Column(spacing=t.GAP, width=None if t.compact else 760, expand=t.compact)
        self.scroll = ft.ListView([ft.Row([self.column], alignment=ft.MainAxisAlignment.CENTER)],
                                  padding=ft.Padding(4, 8, 4, 24), expand=True)
        self.control = t.fade(self.scroll)
        self.render()

    def enter(self, **_) -> None:
        self.shown = True
        self._storage_refresh()

    def leave(self) -> None:
        self.shown = False

    def save(self, name: str, value) -> None:
        setattr(self.app.settings, name, value)
        self.app.settings.save()

    def render(self) -> None:
        s = self.app.settings
        home = lambda: os.path.expanduser("~")   # noqa: E731
        keys = PathField(self.app.picker, home, s.keys, "file", ("keys",), self._keys)
        received = PathField(self.app.picker, home, s.received, "dir", on_change=lambda v: self.save("received", v))
        self._keys(s.keys, update=False)
        speed = t.dropdown([("921600", tr('settings.921600_default_1702d5', '921600 (default)')), ("1500000", tr('settings.1500000_faster_needs_a_good_cable_f5b9b7', '1500000 (faster, needs a good cable)'))],
                           str(s.baud), on_select=lambda e: self.save("baud", int(e.control.value)))

        def number(name, label, valid, size):
            def store(e):
                try:
                    value = int(e.control.value)
                except ValueError:
                    return
                if valid(value):
                    self.save(name, value)
            return ft.Column([t.text(label, 11, t.MUTED),
                              t.field(value=str(getattr(s, name)), mono=True, digits=True, limit=size,
                                      on_change=store)],
                             spacing=4, expand=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        gba = lambda v: 0 <= v <= 65535   # noqa: E731
        trainer = ft.Column([
            ft.Row([
                ft.Column([t.text(tr('settings.name_dcd1d5', 'Name'), 11, t.MUTED),
                           t.field(value=s.ot, limit=12, on_change=lambda e: self.save("ot", e.control.value[:12]))],
                          spacing=4, expand=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Column([t.text(tr('settings.gender_a04630', 'Gender'), 11, t.MUTED),
                           t.dropdown([("0", tr('settings.male_03f8c1', 'Male')), ("1", tr('settings.female_e8cca8', 'Female'))], str(s.gender),
                                      on_select=lambda e: self.save("gender", int(e.control.value)))],
                          spacing=4, expand=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Column([t.text(tr('settings.language_a4fe65', 'Language'), 11, t.MUTED),
                           t.dropdown(list(LANGUAGES), str(s.language),
                                      on_select=lambda e: self.save("language", int(e.control.value)))],
                          spacing=4, expand=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ], spacing=10, intrinsic_height=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
            ft.Row([
                number("tid", tr('settings.id_firered_and_leafgreen_d6b2c2', 'ID, FireRed and LeafGreen'), gba, 5),
                number("sid", tr('settings.secret_id_795924', 'Secret ID'), gba, 5),
                number("switch_tid", tr('settings.id_switch_games_296c3a', 'ID, Switch games'), lambda v: switch_ids_valid(v, s.switch_sid), 6),
                number("switch_sid", tr('settings.secret_id_795924', 'Secret ID'), lambda v: switch_ids_valid(s.switch_tid, v), 4),
            ], spacing=10, intrinsic_height=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        ], spacing=10)

        def switch(name, label, help_):
            return t.card(label, None, help_,
                          trailing=t.switch(getattr(s, name), lambda e: self.save(name, e.control.value)))

        def link(label, url):
            return t.link_button(label, lambda e: self.app.page.run_task(self.app.open_url, url))

        def section(label):
            return ft.Container(t.text(label, 12, t.MUTED, weight=ft.FontWeight.W_600),
                                padding=ft.Padding(4, 8, 0, 0))

        advanced = [
            t.card(tr('settings.serial_speed_1ed128', 'Serial speed'), speed, tr('settings.how_fast_the_computer_talks_to_the_board_keep_the_defau_4942ca', 'How fast the computer talks to the board. Keep the default unless a guide says otherwise.')),
            switch("board_trace", tr('settings.record_the_board_s_serial_traffic_e599a1', "Record the board's serial traffic"),
                   tr('settings.adds_the_board_s_counters_and_every_serial_message_to_t_615de0', "Adds the board's counters and every serial message to the session record. Only for radio problems someone asked you to report.")),
            t.card(tr('settings.home_tracker_2e98ab', 'HOME tracker'), t.dropdown([("empty", tr('settings.leave_it_empty_default_3eca45', 'Leave it empty (default)')), ("made", tr('settings.make_one_495c86', 'Make one'))],
                                              s.home_tracker, on_select=lambda e: self._home_tracker(e.control.value)),
                   tr('settings.what_the_bank_the_pokemon_builder_and_mystery_gift_simu_2ba22b', 'What the bank, the Pokemon builder and Mystery Gift - Simulated put in the HOME tracker of a Pokemon moved to another game or received from a Mystery Gift. PKHeX flags an empty one; HOME refuses a made one.')),
            t.card(tr('settings.pokemon_sprites_bba928', 'Pokemon sprites'), ft.Row([t.button(tr('settings.clear_the_cache_883bc1', 'Clear the cache'), self._clear_sprites, "refresh",
                                                        filled=False), self.sprite_state], spacing=10),
                   tr('settings.pixel_art_sprites_come_from_pokeapi_and_are_kept_on_thi_a49320', 'Pixel-art sprites come from PokeAPI and are kept on this computer after the first download. The app works without them.'),
                   trailing=t.switch(s.sprites, lambda e: self.save("sprites", e.control.value))),
        ]
        self.column.controls = [
            ft.Container(ft.Row([t.pixel_icon("gear", size=24, color=t.RED),
                                 t.text(tr('settings.settings_74a883', 'Settings'), 22, weight=ft.FontWeight.W_600)], spacing=10),
                         padding=ft.Padding(4, 12, 0, 0)),
            section(tr('settings.your_setup_d0e2ca', 'Your setup')),
            t.card(tr('settings.app_language_b8352b', 'App language'), t.dropdown(
                [("", tr('settings.english_ba118b', 'English')), *((p.id, p.name) for p in plugins.discover() if p.locale and not p.error)],
                s.app_language, on_select=lambda e: self._language(e.control.value)),
                tr('settings.community_language_packs_restart_pokeldn_to_apply_this__f11c09', 'Community language packs. Restart pokeldn to apply this choice.')),
            t.card(tr('settings.switch_keys_f1b42d', 'Switch keys'), ft.Column([keys.control, self.keys_state], spacing=8),
                   tr('settings.prod_keys_dumped_from_your_own_console_needed_to_talk_t_26673c', 'prod.keys dumped from your own console. Needed to talk to the games; it never leaves this computer.')),
            t.card(tr('settings.your_trainer_d70afb', 'Your trainer'), trainer,
                   tr('settings.the_original_trainer_of_every_pokemon_the_app_builds_fo_3e4326', 'The original trainer of every Pokemon the app builds for you. Put your own name, gender and IDs to make them yours, so a traded Pokemon keeps its friendship: FireRed and LeafGreen show a five-digit ID, the Switch games a six-digit one. The IDs were drawn at random on first launch.')),
            t.card(tr('settings.received_pokemon_1d657d', 'Received Pokemon'), ft.Row([ft.Container(received.control, expand=True),
                                               t.icon_button("external-link",
                                                             lambda e: open_folder(os.path.expanduser(s.received)),
                                                             tr('settings.open_it_acfe1b', 'Open it'))]),
                   tr('settings.where_the_pokemon_a_console_sends_you_are_saved_29cb57', 'Where the Pokemon a console sends you are saved.')),
            section(tr('settings.storage_a69c4d', 'Storage')),
            t.card(tr('settings.local_files_3eb956', 'Local files'), ft.Column([
                self.storage_state,
                ft.Row([self.clear_button], spacing=10),
                self.storage_result,
            ], spacing=8),
                   tr('settings.free_space_used_by_session_records_logs_temporary_offer_f7ffba', 'Free space used by session records, logs, temporary offers and unused built Pokemon. Your received Pokemon, selected offers, keys, firmware and settings are kept.')),
            section(tr('settings.bug_reports_aa0e58', 'Bug reports')),
            t.card(tr('settings.record_every_session_f5f9d8', 'Record every session'), ft.Row([t.button(tr('settings.open_the_records_6fade1', 'Open the records'), lambda e: open_folder(
                str(SESSION / "captures")), "folder", filled=False)]),
                   tr('settings.keeps_a_small_record_of_each_session_when_something_fai_b8e93e', 'Keeps a small record of each session. When something fails, attach the latest file to your report.'),
                   trailing=t.switch(s.capture, lambda e: self.save("capture", e.control.value))),
            switch("private_logs", tr('settings.private_logs', 'Hide personal details in logs'),
                   tr('settings.private_logs_detail', 'Masks trainer names, nicknames, trainer IDs, the device half of MAC addresses and your user folder in the logs shown here, so you can share them or record your screen. Turn it off only if a developer asks for the full log.')),
            ft.Row([t.link_button(tr('settings.hide_advanced_settings_82557c', 'Hide advanced settings') if self.show_advanced else tr('settings.show_advanced_settings_c0d5bf', 'Show advanced settings'),
                                  self._toggle_advanced)]),
            *(advanced if self.show_advanced else []),
            t.card(tr('settings.updates_22e2ba', 'Updates'), ft.Row([t.button(tr('settings.check_now_2937cf', 'Check now'), self._check_update, "refresh", filled=False),
                                      self.update_state], spacing=10),
                   tr('settings.asks_github_for_a_newer_pokeldn_when_the_app_starts_and_b07880', "Asks GitHub for a newer pokeldn when the app starts, and each installed plugin's own address for a newer version of it. Nothing about you or your games is sent."),
                   trailing=t.switch(s.check_updates, lambda e: self.save("check_updates", e.control.value))),
            t.card(tr('settings.about_pokeldn_7bfa4b', 'About pokeldn {value0}', value0=__version__), ft.Row([link(label, url) for label, url in LINKS], spacing=4),
                   tr('settings.pokeldn_is_agplv3_pokemon_are_checked_with_pkhex_core_g_689838', 'pokeldn is AGPLv3. Pokemon are checked with PKHeX.Core (GPLv3).')),
        ]

    def _language(self, plugin_id: str) -> None:
        if plugin_id and plugin_id not in self.app.settings.plugins:
            self.save("plugins", [*self.app.settings.plugins, plugin_id])
        self.save("app_language", plugin_id)

    def _home_tracker(self, value: str) -> None:
        self.save("home_tracker", value)
        pokemon.SERVICE.home_tracker = value

    def _toggle_advanced(self, e) -> None:
        self.show_advanced = not self.show_advanced
        self.render()
        self.control.update()

    def _check_update(self, e) -> None:
        self.asked = True
        self.app.check_update()
        self._update_text()
        self.update_state.update()

    def _update_text(self) -> None:
        release, state = self.app.update, self.app.update_state
        self.update_state.value = {
            "checking": tr('settings.checking_2e5f79', 'Checking...'),
            "current": tr('settings.latest_version', 'You have the latest version ({value0}).', value0=__version__),
            "offline": tr('settings.github_did_not_answer_check_your_connection_c1e29b', 'GitHub did not answer. Check your connection.'),
            "available": tr('settings.version_available', 'pokeldn {value0} is available.', value0=release.version) if release else "",
        }.get(state, "")
        self.update_state.color = t.GREEN if state == "available" else t.MUTED

    def _update_shown(self) -> None:
        self._update_text()
        if self.shown:
            self.update_state.update()
            if self.asked and self.app.update:
                self.app.navigate("update")
        self.asked = False

    def _clear_sprites(self, e) -> None:
        self.sprite_state.value = tr('settings.files_removed_78e092', '{value0} files removed', value0=CACHE.clear())
        self.sprite_state.update()

    def _storage_refresh(self, inventory=None) -> None:
        if self.storage_work:
            return
        self.storage_work = True
        self.clear_button.disabled = True
        self.storage_state.value = tr('settings.clearing_local_files_a2d4fd', 'Clearing local files...') if inventory is not None else tr('settings.checking_local_files_77c76c', 'Checking local files...')
        if self.shown:
            self.app.ui(self.control.update)
        settings = copy.deepcopy(self.app.settings)

        def work():
            try:
                result = storage.clear(inventory, settings) if inventory is not None else None
                found = storage.scan(settings)
                self.app.ui(lambda: self._storage_done(found, result))
            except OSError as error:
                self.app.ui(lambda message=str(error): self._storage_done(storage.Inventory(errors=1),
                                                                          error=message))
            finally:
                if inventory is not None:
                    self.app.storage_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _storage_done(self, inventory, result=None, error="") -> None:
        self.storage_work = False
        self.storage_inventory = inventory
        count = len(inventory.files)
        self.clear_button.disabled = not count
        self.storage_state.value = (tr('settings.can_be_freed_files_57c49a', '{value0} can be freed · {value1} files', value0=storage.size_text(inventory.size), value1=count)
                                    if count else tr('settings.no_local_files_to_clear_9fe2b9', 'No local files to clear.'))
        if inventory.errors:
            self.storage_state.value += tr('settings.some_folders_could_not_be_read_a6ffe1', ' Some folders could not be read.')
        if result is not None:
            self.storage_result.value = tr('settings.freed_files_removed_abb414', 'Freed {value0} · {value1} files removed.', value0=storage.size_text(result.size), value1=result.files)
            if result.errors:
                self.storage_result.value += tr('settings.files_could_not_be_removed_try_again_0e7489', ' {value0} files could not be removed; try again.', value0=result.errors)
            if result.skipped:
                self.storage_result.value += tr('settings.files_in_use_or_changed_since_the_check_were_kept_b24a31', ' Files in use or changed since the check were kept.')
        if error:
            self.storage_result.value = tr('settings.could_not_clear_local_files_7e6283', 'Could not clear local files: {value0}', value0=error)
        self.storage_result.visible = bool(self.storage_result.value)
        if self.shown:
            self.control.update()

    def _clear_local(self, e) -> None:
        if self.storage_work:
            return
        if self.app.busy:
            self.storage_result.value = tr('settings.finish_the_current_run_or_board_check_before_clearing_l_0e8d2c', 'Finish the current run or board check before clearing local files.')
            self.storage_result.visible = True
            self.storage_result.update()
            return
        inventory = self.storage_inventory
        if not inventory.files:
            self._storage_refresh()
            return

        def close(e):
            self.app.page.pop_dialog()

        def clear(e):
            close(e)
            if self.app.busy or self.storage_work:
                self.storage_result.value = tr('settings.finish_the_current_run_or_board_check_before_clearing_l_0e8d2c', 'Finish the current run or board check before clearing local files.')
                self.storage_result.visible = True
                self.storage_result.update()
                return
            self.app.storage_busy = True
            self._storage_refresh(inventory)

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('settings.clear_local_files_5d39aa', 'Clear local files?'), 17, weight=ft.FontWeight.W_600),
            content=ft.Container(t.text(
                tr('settings.remove_files_and_free_about_this_deletes_saved_session__3f93fe', 'Remove {value0} files and free about {value1}. This deletes saved session records, logs, temporary offers and unused built Pokemon. Save any records needed for a bug report first. Your received Pokemon, selected offers, keys, firmware and settings are kept.', value0=len(inventory.files), value1=storage.size_text(inventory.size)), 13, t.MUTED), width=460),
            actions=[t.secondary_button(tr('settings.cancel_19766e', 'Cancel'), close), t.button(tr('settings.clear_files_a16c81', 'Clear files'), clear)],
        ))

    def _keys(self, value: str, update: bool = True) -> None:
        self.save("keys", value)
        ok = keys_found(value)
        self.keys_state.content = ft.Row([
            t.pixel_icon("checkbox-on" if ok else "warning-diamond",
                    color=t.GREEN if ok else t.RED),
            t.text(tr('settings.found_b0ee31', 'Found') if ok else tr('settings.no_file_at_this_path_f6f154', 'No file at this path'), 12, t.GREEN if ok else t.RED)], spacing=6)
        if update:
            self.keys_state.update()
