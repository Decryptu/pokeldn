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
from pokeldn.app.i18n import text as tr, ref

LANGUAGES = (("2", ref('core.settings.language_english')),
             ("3", ref('core.settings.language_french')),
             ("5", ref('core.settings.language_german')),
             ("4", ref('core.settings.language_italian')),
             ("7", ref('core.settings.language_spanish')),
             ("1", ref('core.settings.language_japanese')),
             ("8", ref('core.settings.language_korean')),
             ("9", ref('core.settings.language_simplified_chinese')),
             ("10", ref('core.settings.language_traditional_chinese')))

LINKS = ((ref('core.settings.documentation_c20592'), "https://decryptu.github.io/pokeldn/"),
         (ref('core.settings.github_f911e4'), "https://github.com/Decryptu/pokeldn"),
         (ref('core.settings.discord_053bc6'), "https://discord.gg/PyvaVYnpXC"))


class SettingsView:
    def __init__(self, app):
        self.app = app
        self.keys_state = ft.Container()
        self.sprite_state = t.text("", 12, t.MUTED)
        self.update_state = t.text("", 12, t.MUTED)
        self.storage_state = t.text(tr('core.settings.checking_local_files_77c76c'), 12, t.MUTED)
        self.storage_result = t.text("", 12, t.MUTED, visible=False)
        self.storage_inventory = storage.Inventory()
        self.storage_work = False
        self.clear_button = t.button(tr('core.settings.clear_local_files_2f0392'), self._clear_local, "folder", filled=False,
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
        self.language_control = t.dropdown(self.language_choices(),
                s.app_language + ("|" + s.app_locale if s.app_locale else ""),
                on_select=lambda e: self._language(e.control.value))
        home = lambda: os.path.expanduser("~")   # noqa: E731
        keys = PathField(self.app.picker, home, s.keys, "file", ("keys",), self._keys)
        received = PathField(self.app.picker, home, s.received, "dir", on_change=lambda v: self.save("received", v))
        self._keys(s.keys, update=False)
        speed = t.dropdown([("921600", tr('core.settings.921600_default_1702d5')), ("1500000", tr('core.settings.1500000_faster_needs_a_good_cable_f5b9b7'))],
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
                ft.Column([t.text(tr('core.settings.name_dcd1d5'), 11, t.MUTED),
                           t.field(value=s.ot, limit=12, on_change=lambda e: self.save("ot", e.control.value[:12]))],
                          spacing=4, expand=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Column([t.text(tr('core.settings.gender_a04630'), 11, t.MUTED),
                           t.dropdown([("0", tr('core.settings.male_03f8c1')), ("1", tr('core.settings.female_e8cca8'))], str(s.gender),
                                      on_select=lambda e: self.save("gender", int(e.control.value)))],
                          spacing=4, expand=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Column([t.text(tr('core.settings.language_a4fe65'), 11, t.MUTED),
                           t.dropdown(list(LANGUAGES), str(s.language),
                                      on_select=lambda e: self.save("language", int(e.control.value)))],
                          spacing=4, expand=True, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ], spacing=10, intrinsic_height=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
            ft.Row([
                number("tid", tr('core.settings.id_firered_and_leafgreen_d6b2c2'), gba, 5),
                number("sid", tr('core.settings.secret_id_795924'), gba, 5),
                number("switch_tid", tr('core.settings.id_switch_games_296c3a'), lambda v: switch_ids_valid(v, s.switch_sid), 6),
                number("switch_sid", tr('core.settings.secret_id_795924'), lambda v: switch_ids_valid(s.switch_tid, v), 4),
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
            t.card(tr('core.settings.serial_speed_1ed128'), speed, tr('core.settings.how_fast_the_computer_talks_to_the_board_keep_the_defau_4942ca')),
            switch("board_trace", tr('core.settings.record_the_board_s_serial_traffic_e599a1'),
                   tr('core.settings.adds_the_board_s_counters_and_every_serial_message_to_t_615de0')),
            t.card(tr('core.settings.home_tracker_2e98ab'), t.dropdown([("empty", tr('core.settings.leave_it_empty_default_3eca45')), ("made", tr('core.settings.make_one_495c86'))],
                                              s.home_tracker, on_select=lambda e: self._home_tracker(e.control.value)),
                   tr('core.settings.what_the_bank_the_pokemon_builder_and_mystery_gift_simu_2ba22b')),
            t.card(tr('core.settings.pokemon_sprites_bba928'), ft.Row([t.button(tr('core.settings.clear_the_cache_883bc1'), self._clear_sprites, "refresh",
                                                        filled=False), self.sprite_state], spacing=10),
                   tr('core.settings.pixel_art_sprites_come_from_pokeapi_and_are_kept_on_thi_a49320'),
                   trailing=t.switch(s.sprites, lambda e: self.save("sprites", e.control.value))),
        ]
        self.column.controls = [
            ft.Container(ft.Row([t.pixel_icon("gear", size=24, color=t.RED),
                                 t.text(tr('core.settings.settings_74a883'), 22, weight=ft.FontWeight.W_600)], spacing=10),
                         padding=ft.Padding(4, 12, 0, 0)),
            section(tr('core.settings.your_setup_d0e2ca')),
            t.card(tr('core.settings.app_language_b8352b'), self.language_control,
                tr('core.settings.language_help')),
            t.card(tr('core.settings.switch_keys_f1b42d'), ft.Column([keys.control, self.keys_state], spacing=8),
                   tr('core.settings.prod_keys_dumped_from_your_own_console_needed_to_talk_t_26673c')),
            t.card(tr('core.settings.your_trainer_d70afb'), trainer,
                   tr('core.settings.the_original_trainer_of_every_pokemon_the_app_builds_fo_3e4326')),
            t.card(tr('core.settings.received_pokemon_1d657d'), ft.Row([ft.Container(received.control, expand=True),
                                               t.icon_button("external-link",
                                                             lambda e: open_folder(os.path.expanduser(s.received)),
                                                             tr('core.settings.open_it_acfe1b'))]),
                   tr('core.settings.where_the_pokemon_a_console_sends_you_are_saved_29cb57')),
            section(tr('core.settings.storage_a69c4d')),
            t.card(tr('core.settings.local_files_3eb956'), ft.Column([
                self.storage_state,
                ft.Row([self.clear_button], spacing=10),
                self.storage_result,
            ], spacing=8),
                   tr('core.settings.free_space_used_by_session_records_logs_temporary_offer_f7ffba')),
            section(tr('core.settings.bug_reports_aa0e58')),
            t.card(tr('core.settings.record_every_session_f5f9d8'), ft.Row([t.button(tr('core.settings.open_the_records_6fade1'), lambda e: open_folder(
                str(SESSION / "captures")), "folder", filled=False)]),
                   tr('core.settings.keeps_a_small_record_of_each_session_when_something_fai_b8e93e'),
                   trailing=t.switch(s.capture, lambda e: self.save("capture", e.control.value))),
            switch("private_logs", tr('core.settings.private_logs'),
                   tr('core.settings.private_logs_detail')),
            ft.Row([t.link_button(tr('core.settings.hide_advanced_settings_82557c') if self.show_advanced else tr('core.settings.show_advanced_settings_c0d5bf'),
                                  self._toggle_advanced)]),
            *(advanced if self.show_advanced else []),
            t.card(tr('core.settings.updates_22e2ba'), ft.Row([t.button(tr('core.settings.check_now_2937cf'), self._check_update, "refresh", filled=False),
                                      self.update_state], spacing=10),
                   tr('core.settings.asks_github_for_a_newer_pokeldn_when_the_app_starts_and_b07880'),
                   trailing=t.switch(s.check_updates, lambda e: self.save("check_updates", e.control.value))),
            t.card(tr('core.settings.about_pokeldn_7bfa4b', value0=__version__), ft.Row([link(label, url) for label, url in LINKS], spacing=4),
                   tr('core.settings.pokeldn_is_agplv3_pokemon_are_checked_with_pkhex_core_g_689838')),
        ]

    def _language(self, plugin_id: str) -> None:
        from pokeldn.app import i18n
        plugin_id, _, locale = plugin_id.partition("|")
        if plugin_id and plugin_id != i18n.BUILTIN_CHINESE and plugin_id not in self.app.settings.plugins:
            self.save("plugins", [*self.app.settings.plugins, plugin_id])
        try:
            i18n.select(plugin_id, locale or None, strict=True)
        except ValueError as error:
            control = getattr(self, "language_control", None)
            if control is not None:
                current = self.app.settings
                control.value = current.app_language + ("|" + current.app_locale if current.app_locale else "")
                control.update()
            self.app.page.show_dialog(ft.SnackBar(t.text(tr("core.settings.language_failed", pack=plugin_id, reason=str(error)))))
            return
        self.save("app_language", plugin_id)
        self.save("app_locale", locale)

    def language_choices(self):
        from pokeldn.app import i18n
        choices = [("", tr('core.settings.english_ba118b')), (i18n.BUILTIN_CHINESE, "简体中文")]
        for plugin in plugins.discover():
            if plugin.locale and not plugin.error:
                locales = plugin.resources.get("locales", {})
                choices.extend((plugin.id + "|" + tag, spec["name"]) for tag, spec in locales.items())
                if not locales:
                    choices.append((plugin.id, plugin.name))
        return choices

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
            "checking": tr('core.settings.checking_2e5f79'),
            "current": tr('core.settings.latest_version', value0=__version__),
            "offline": tr('core.settings.github_did_not_answer_check_your_connection_c1e29b'),
            "available": tr('core.settings.version_available', value0=release.version) if release else "",
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
        self.sprite_state.value = tr('core.settings.files_removed_78e092', value0=CACHE.clear())
        self.sprite_state.update()

    def _storage_refresh(self, inventory=None) -> None:
        if self.storage_work:
            return
        self.storage_work = True
        self.clear_button.disabled = True
        self.storage_state.value = tr('core.settings.clearing_local_files_a2d4fd') if inventory is not None else tr('core.settings.checking_local_files_77c76c')
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
        self.storage_state.value = (tr('core.settings.can_be_freed_files_57c49a', value0=storage.size_text(inventory.size), value1=count)
                                    if count else tr('core.settings.no_local_files_to_clear_9fe2b9'))
        if inventory.errors:
            self.storage_state.value += tr('core.settings.some_folders_could_not_be_read_a6ffe1')
        if result is not None:
            self.storage_result.value = tr('core.settings.freed_files_removed_abb414', value0=storage.size_text(result.size), value1=result.files)
            if result.errors:
                self.storage_result.value += tr('core.settings.files_could_not_be_removed_try_again_0e7489', value0=result.errors)
            if result.skipped:
                self.storage_result.value += tr('core.settings.files_in_use_or_changed_since_the_check_were_kept_b24a31')
        if error:
            self.storage_result.value = tr('core.settings.could_not_clear_local_files_7e6283', value0=error)
        self.storage_result.visible = bool(self.storage_result.value)
        if self.shown:
            self.control.update()

    def _clear_local(self, e) -> None:
        if self.storage_work:
            return
        if self.app.busy:
            self.storage_result.value = tr('core.settings.finish_the_current_run_or_board_check_before_clearing_l_0e8d2c')
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
                self.storage_result.value = tr('core.settings.finish_the_current_run_or_board_check_before_clearing_l_0e8d2c')
                self.storage_result.visible = True
                self.storage_result.update()
                return
            self.app.storage_busy = True
            self._storage_refresh(inventory)

        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('core.settings.clear_local_files_5d39aa'), 17, weight=ft.FontWeight.W_600),
            content=ft.Container(t.text(
                tr('core.settings.remove_files_and_free_about_this_deletes_saved_session__3f93fe', value0=len(inventory.files), value1=storage.size_text(inventory.size)), 13, t.MUTED), width=460),
            actions=[t.secondary_button(tr('core.settings.cancel_19766e'), close), t.button(tr('core.settings.clear_files_a16c81'), clear)],
        ))

    def _keys(self, value: str, update: bool = True) -> None:
        self.save("keys", value)
        ok = keys_found(value)
        self.keys_state.content = ft.Row([
            t.pixel_icon("checkbox-on" if ok else "warning-diamond",
                    color=t.GREEN if ok else t.RED),
            t.text(tr('core.settings.found_b0ee31') if ok else tr('core.settings.no_file_at_this_path_f6f154'), 12, t.GREEN if ok else t.RED)], spacing=6)
        if update:
            self.keys_state.update()
