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
TYPE_LIMIT = 100_000                # seeds tried for a type: about two minutes, 1 ms each


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
        self.type_id, self.kind, self._cancel, self._searching = None, "of", False, False
        self.type_pick = t.dropdown([(str(i), translate(name)) for i, name in enumerate(lair.TYPES)], None,
                                    on_select=lambda e: setattr(self, "type_id", int(e.control.value)),
                                    menu_height=320, hint_text=tr('lair_seed.a_type_8d3f60', 'A type'))
        self.rank = t.dropdown([("of", tr('lair_seed.encounters_of_this_type_5e1a94', 'Encounters of this type')),
                                ("weak", tr('lair_seed.encounters_weak_to_this_type_b72c08', 'Encounters weak to this type'))],
                               "of", on_select=lambda e: setattr(self, "kind", e.control.value))
        self.status = t.text("", 12, t.MUTED)
        self.by_type = t.secondary_button(tr('lair_seed.search_by_type_c40e7b', 'Search by type'), self._find_type, "search")
        self.preview = ft.Column(spacing=8, tight=True)
        buttons = ft.Row([t.secondary_button(tr('lair_seed.new_seed_4c0d9a', 'New seed'), self._roll, "shuffle"),
                          t.secondary_button(tr('lair_seed.find_a_seed_2f7e15', 'Find a seed'), self._find, "search"),
                          self.by_type],
                         spacing=8, wrap=True, run_spacing=8)
        self.control = ft.Column([ft.Row([self.seed]), ft.Row([self.wanted]), ft.Row([self.type_pick, self.rank], wrap=True),
                                 buttons, self.status, self.preview],
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

    def _find_type(self, _event) -> None:
        """Rank TYPE_LIMIT random seeds by the ten encounters, not knowing which a path meets
        (docs/swsh_raid.md, The adventure seed); a second press ends the search."""
        if self._searching:
            self._cancel = True
            return
        if self.type_id is None:
            return
        wanted, kind, self._cancel, self._searching = self.type_id, self.kind, False, True
        self.status.value = tr('lair_seed.searching_7a1b33', 'Searching...')
        self.status.update()

        def progress(n):
            self.app.ui(lambda: (setattr(self.status, "value", f"{n} / {TYPE_LIMIT}"), self.status.update()))

        def run():
            seed, score = lair.search(lambda offer, found: lair.type_score(kind, wanted, offer, found),
                                      TYPE_LIMIT, rows=self.rows, progress=progress, cancel=lambda: self._cancel)

            def done():
                self._searching = False
                if seed is not None and score[0]:
                    self.status.value = tr('lair_seed.encounters_of_the_ten_c19d52',
                                           '{value0} of the ten encounters, {value1} of the three rentals.',
                                           value0=score[0], value1=score[1])
                    self._set(seed)
                else:
                    self.status.value = tr('lair_seed.no_seed_found_try_again_0c5e8d', 'No seed found; try again.')
                    self.status.update()
            self.app.ui(done)
        threading.Thread(target=run, daemon=True).start()
