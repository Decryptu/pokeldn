"""The Dynamax Adventure seed: the rentals and the Pokemon on the way it gives, a new seed, and a
search for a seed whose offer holds a wanted rental (pokeldn.swsh.lair, docs/swsh_raid.md)."""
from pokeldn.app.i18n import t as tr

import random
import re
import threading

import flet as ft

from gui import theme as t
from gui.localization import translate
from gui.views.sprites import MINI, Sprite
from pokeldn.swsh import lair, raid_event

SEARCH_LIMIT = 5000                 # seeds tried for a wanted rental; one is offered every ~75


def seed_of(text: str) -> int | None:
    return int(text, 16) if re.fullmatch(r"[0-9A-Fa-f]{1,16}", text or "") else None


class LairSeedPicker:
    def __init__(self, app, value: str, on_change):
        self.app, self.on_change = app, on_change
        self.rows = lair.table()
        self.names = raid_event.tables()["species_names"]
        self.seed = t.field(value=str(value or ""), mono=True, expand=True, on_change=self._typed,
                            hint=tr('lair_seed.empty_for_a_random_seed_6d1f0a', 'Empty for a random seed'))
        rentals = sorted({row[0] for row in self.rows if not row[2]}, key=lambda s: self._name(s))
        self.want = None
        self.wanted = t.dropdown([(str(s), self._name(s)) for s in rentals], None, enable_filter=True,
                                 on_select=lambda e: setattr(self, "want", e.control.value),
                                 editable=True, menu_height=320,
                                 hint_text=tr('lair_seed.a_rental_you_want_8e2b71', 'A rental you want'))
        self.status = t.text("", 12, t.MUTED)
        self.preview = ft.Column(spacing=8, tight=True)
        buttons = ft.Row([t.secondary_button(tr('lair_seed.new_seed_4c0d9a', 'New seed'), self._roll, "shuffle"),
                          t.secondary_button(tr('lair_seed.find_a_seed_2f7e15', 'Find a seed'), self._find, "search")],
                         spacing=8, wrap=True, run_spacing=8)
        self.control = ft.Column([ft.Row([self.seed]), ft.Row([self.wanted]), buttons, self.status, self.preview],
                                 spacing=8, tight=True)
        self._show(str(value or ""), update=False)

    def _name(self, species: int) -> str:
        return translate(self.names.get(str(species), f"#{species}"))

    def _tiles(self, rows) -> ft.Row:
        return ft.Row([ft.Column([Sprite(self.app, row[0], size=MINI, form=row[1]).control,
                                  t.text(self._name(row[0]), 11, t.SOFT)],
                                 spacing=2, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
                       for row in rows], spacing=8, run_spacing=8, wrap=True)

    def _show(self, text: str, update: bool = True) -> None:
        seed = seed_of(text)
        self.seed.error = (None if not text or seed is not None
                           else tr('lair_seed.up_to_sixteen_hexadecimal_digits_3a91c4', 'Up to sixteen hexadecimal digits.'))
        self.preview.controls = []
        if seed is not None:
            offer, encounters = lair.adventure(seed, rows=self.rows)
            self.preview.controls = [
                t.labeled_control(tr('lair_seed.rentals_offered_5b8d02', 'Rentals offered'), self._tiles(offer[:3])),
                t.labeled_control(tr('lair_seed.pokemon_on_the_way_1e6c47', 'Pokemon on the way'), self._tiles(encounters))]
        if update:
            self.control.update()

    def _set(self, seed: int) -> None:
        self.seed.value = f"{seed:016X}"
        self.on_change(self.seed.value)
        self._show(self.seed.value)

    def _typed(self, event) -> None:
        event.control.value = event.control.value.upper()
        self.on_change(event.control.value)
        self._show(event.control.value)

    def _roll(self, _event) -> None:
        self._set(random.SystemRandom().getrandbits(64))

    def _find(self, _event) -> None:
        if not self.want:
            return
        species = int(self.want)
        self.status.value = tr('lair_seed.searching_7a1b33', 'Searching...')
        self.status.update()

        def run():
            rand = random.SystemRandom()
            found = None
            for _ in range(SEARCH_LIMIT):
                seed = rand.getrandbits(64)
                if species in [row[0] for row in lair.adventure(seed, rows=self.rows)[0][:3]]:
                    found = seed
                    break

            def done():
                self.status.value = ("" if found is not None else
                                     tr('lair_seed.no_seed_found_try_again_0c5e8d', 'No seed found; try again.'))
                if found is not None:
                    self._set(found)
                else:
                    self.status.update()
            self.app.ui(done)
        threading.Thread(target=run, daemon=True).start()
