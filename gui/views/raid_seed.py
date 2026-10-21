"""The raid seed field: the boss and rewards the seed gives in the chosen context, and a finder that
searches seeds by what the boss is and the rewards it gives (pokeldn.sv.raid_search). An event's
context (its `event`, `group` and `den`) draws from the event and narrows the finder to what the
event spawns."""
from pokeldn.app.i18n import t as tr

import random
import re
import threading
import time

import flet as ft

from gui import theme as t
from gui.views.pokemon import NamePicker
from gui.views.reward_filter import RewardFilter
from gui.views.sprites import MINI, SIZE, Sprite
from gui.views.widgets import Check, PixelActivity
from gui.localization import SERVICE, error_message, translate
from pokeldn.sv import raid_encounter, raid_event, raid_search
from pokeldn.sv.raid_encounter import NATURES as NATURES_EN, TERA_TYPES as TERA_TYPES_EN
NATURES = tuple(translate(name) for name in NATURES_EN)
TERA_TYPES = tuple(translate(name) for name in TERA_TYPES_EN)
VERSIONS = {key: translate(name) for key, name in (("scarlet", "Scarlet"), ("violet", "Violet"))}
REGIONS = {key: translate(name) for key, name in (("paldea", "Paldea"), ("kitakami", "Kitakami"), ("blueberry", "Blueberry Academy"))}
GENDERS = (tr('raid_seed.male_03f8c1', 'Male'), tr('raid_seed.female_e8cca8', 'Female'), tr('raid_seed.genderless_300b01', 'Genderless'))
STATS = (tr('raid_seed.hp_9449a7', 'HP'), tr('raid_seed.atk_f231c4', 'Atk'), tr('raid_seed.def_fcc0fc', 'Def'), tr('raid_seed.spe_80f7bc', 'Spe'), tr('raid_seed.spa_099d09', 'SpA'), tr('raid_seed.spd_08fc8c', 'SpD'))
SIZE_MARKS = {0: "Mini", 0xFF: "Jumbo"}      # a boss's scale -> the size mark it is eligible for
PROGRESS = (("beginning", tr('raid_seed.beginning_9e6b41', 'Beginning')), ("tera", tr('raid_seed.tera_raids_unlocked_07d442', 'Tera Raids unlocked')), ("3star", tr('raid_seed.3_star_raids_e72615', '3-star raids')),
            ("4star", tr('raid_seed.4_star_raids_d82c77', '4-star raids')), ("5star", tr('raid_seed.5_star_raids_d693f5', '5-star raids')), ("6star", tr('raid_seed.6_star_raids_e7e30a', '6-star raids')))
ALL_SEEDS = 1 << 32


def seed_of(text: str) -> int | None:
    return int(text, 16) if re.fullmatch(r"[0-9A-Fa-f]{8}", text or "") else None


def duration(seconds: float) -> str:
    """-> 45 s, 3 min 20 s or 2 h 5 min."""
    seconds = int(seconds)
    if seconds < 60:
        return tr('raid_seed.s_d05609', '{value0} s', value0=seconds)
    if seconds < 3600:
        return tr('raid_seed.min_s_d1a892', '{value0} min {value1} s', value0=seconds // 60, value1=seconds % 60)
    return tr('raid_seed.h_min_2e98a9', '{value0} h {value1} min', value0=seconds // 3600, value1=seconds % 3600 // 60)


def searching(done: int, total: int, elapsed: float) -> str:
    """-> how far a search is, its speed and the time it has left."""
    if not done or elapsed <= 0:
        return tr('raid_seed.searching_of_seeds_ca9ec2', 'Searching {value0:,} of {value1:,} seeds...', value0=done, value1=total)
    rate = done / elapsed
    # A billion once the millions would show 1000.0.
    speed = (tr('raid_seed.billion_190019', '{value0:.2f} billion', value0=rate / 1000000000.0) if round(rate / 1e6, 1) >= 1000
             else tr('raid_seed.million_2bd4f9', '{value0:.1f} million', value0=rate / 1000000.0) if rate >= 1e6 else f"{rate:,.0f}")
    return tr('raid_seed.searching_of_seeds_a_second_left_9b8ab1', 'Searching {value0:,} of {value1:,} seeds, {value2} a second, {value3} left...', value0=done, value1=total, value2=speed, value3=duration((total - done) / rate))


def iv_range(text: str) -> tuple[int, int]:
    """'' any, '31' exactly, '20-31' a range."""
    text = (text or "").strip()
    if not text:
        return 0, 31
    match = re.fullmatch(r"(\d{1,2})(?:\s*-\s*(\d{1,2}))?", text)
    low, high = (int(match.group(1)), int(match.group(2) or match.group(1))) if match else (1, 0)
    if not 0 <= low <= high <= 31:
        raise ValueError(tr('raid_seed.an_iv_is_blank_a_value_from_0_to_31_or_a_range_such_as__c3102f', 'An IV is blank, a value from 0 to 31, or a range such as 20-31.'))
    return low, high


CRYSTALS = {"standard": tr('raid_seed.standard_crystal_3b5674', 'Standard crystal'), "black": tr('raid_seed.black_crystal_42f500', 'Black crystal'), "event": tr('raid_seed.event_crystal_609824', 'Event crystal'),
            "might": tr('raid_seed.seven_star_event_crystal_2ea5df', 'Seven-star event crystal')}


def crystal_colors(context) -> tuple[str, str]:
    return t.BRAND_RED if context["content"] in ("black", "might") else t.BRAND_BLUE


def stars_row(count: int, context) -> ft.ShaderMask:
    """The raid's stars as pixel stars in the crystal's brand gradient: blue standard, red black."""
    return t.tinted(ft.Row([t.pixel_icon("star", color="#FFFFFF") for _ in range(count)], spacing=1,
                           tight=True), crystal_colors(context))


def framed_sprite(app, species: int, shiny: bool, size: int, context) -> ft.Container:
    """The sprite inside a ring of the crystal's gradient."""
    sprite = Sprite(app, species, shiny, size=size)
    sprite.frame.border = None
    radius = 12 if size >= SIZE else 10
    return ft.Container(sprite.control, padding=1.5, border_radius=radius + 1.5,
                        gradient=ft.LinearGradient(begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT,
                                                   colors=list(crystal_colors(context))),
                        shadow=ft.BoxShadow(blur_radius=18, spread_radius=-6,
                                            color=ft.Colors.with_opacity(0.45, crystal_colors(context)[1])))


def iv_tile(label: str, iv: int, stat: int, compact: bool) -> ft.Container:
    """One stat: its IV large (blue at 31, red at 0), a bar of IV out of 31, the stat at the boss's level."""
    color = t.BLUE if iv == 31 else t.RED if iv == 0 else t.TEXT
    bar = ft.ProgressBar(value=iv / 31, color=t.BLUE, bgcolor=ft.Colors.with_opacity(0.08, "#FFFFFF"),
                         bar_height=3, border_radius=2)
    rows = [t.text(label, 10, t.MUTED, weight=ft.FontWeight.W_600),
            t.text(str(iv), 13 if compact else 17, color, weight=ft.FontWeight.W_700), bar]
    if not compact:
        rows.append(t.text(f"{stat}", 10, t.FAINT, tooltip=tr('raid_seed.the_stat_at_the_boss_s_level_f98bbf', "The stat at the boss's level")))
    return ft.Container(ft.Column(rows, spacing=3 if compact else 4, tight=True,
                                  horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                        width=46 if compact else 62, padding=ft.Padding(6, 6, 6, 8), border_radius=10,
                        bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"))


def reward_chips(names: dict[int, str] | None, rewards) -> ft.Control:
    """The rewards as item chips, one per item with the quantities summed, in the raid's order."""
    if names is None:
        return ft.Row([PixelActivity(tr('raid_seed.naming_the_rewards_7a4bbf', 'Naming the rewards')), t.text(tr('raid_seed.naming_the_rewards_7ba442', 'Naming the rewards...'), 12, t.MUTED)],
                      spacing=8)
    totals: dict[int, int] = {}
    for item, quantity in rewards:
        totals[item] = totals.get(item, 0) + quantity
    return ft.Row([ft.Container(ft.Row([
        t.text(names.get(item, tr("presentation.item_number", "Item {number}", number=item)), 12, t.SOFT),
        t.text(f"×{quantity}", 12, t.BLUE, weight=ft.FontWeight.W_700)], spacing=6, tight=True),
        padding=ft.Padding(10, 4, 10, 4), border_radius=999, bgcolor=ft.Colors.with_opacity(0.06, "#FFFFFF"))
        for item, quantity in totals.items()], spacing=6, run_spacing=6, wrap=True)


ACTION_ICONS = {"shield": "shield", "move": "sword", "boss_reset": "refresh", "player_reset": "refresh",
                "drain": "diamond-gem"}
# The scripted actions stand as wide as the sprite and IV tiles above them, so a full-screen card keeps
# each trigger beside its action; a narrower card narrows them.
ACTIONS_WIDTH = 520


def action_label(action, boss: str, moves: dict[int, str]) -> str:
    return {"shield": tr('raid_seed.shield_activation_2f21f1', 'Shield activation'),
            "boss_reset": tr('raid_seed.stats_status_reset_62fa08', '{value0} stats & status reset', value0=boss),
            "player_reset": tr('raid_seed.players_stats_status_reset_bd1ac1', "Players' stats & status reset"),
            "drain": tr('raid_seed.tera_orb_charge_drained_c89279', 'Tera Orb charge drained'),
            "move": tr('raid_seed.uses_fbac7f', '{value0} uses {value1}', value0=boss,
                       value1=moves.get(action.move, tr("presentation.move_number", "Move {number}", number=action.move)))}[action.kind]


def action_rows(moves: dict[int, str] | None, boss: str, actions) -> ft.Control:
    """The boss's scripted actions, one row each: what it does, and the HP or time left that brings it."""
    if moves is None and any(a.kind == "move" for a in actions):
        return ft.Row([PixelActivity(tr('raid_seed.naming_the_moves_37e0da', 'Naming the moves')), t.text(tr('raid_seed.naming_the_moves_8b1cc9', 'Naming the moves...'), 12, t.MUTED)],
                      spacing=8)
    if not actions:
        return t.text(tr('raid_seed.no_scripted_actions_c5dd05', 'No scripted actions.'), 12, t.MUTED)
    # Each trigger on a line of its own, so the label wraps before the row overflows a narrow card.
    return ft.Column([ft.Container(ft.Row([
        t.pixel_icon(ACTION_ICONS[action.kind], size=12, color=t.MUTED),
        ft.Container(t.text(action_label(action, boss, moves or {}), 12, t.SOFT), expand=True),
        ft.Column([ft.Row([t.text(f"{percent}%", 12, t.BLUE, weight=ft.FontWeight.W_700),
                           t.text(tr('raid_seed.hp_remaining_ae9c7b', 'HP remaining') if timing == "hp" else tr('raid_seed.time_remaining_03ba62', 'time remaining'), 12, t.MUTED)],
                          spacing=4, tight=True)
                   for timing, percent in action.triggers], spacing=2, tight=True,
                  horizontal_alignment=ft.CrossAxisAlignment.END)],
        spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding(10, 6, 10, 6), border_radius=8, bgcolor=ft.Colors.with_opacity(0.04, "#FFFFFF"))
        for action in actions], spacing=4, tight=True, width=ACTIONS_WIDTH)


def boss_card(app, seed, stars, boss, context, *, compact=False, rewards=None, actions=None, on_use=None):
    """The boss a seed gives: sprite, stars, level, Tera type, IVs over stats, nature, context."""
    shiny = (boss["trainer_id"] ^ boss["secret_id"] ^ (boss["pid"] >> 16) ^ (boss["pid"] & 0xFFFF)) < 16
    name = translate(raid_encounter.tables()["species_names"][str(boss["species"])])
    title = [t.text(name, 14 if compact else 17, weight=ft.FontWeight.W_700)]
    if shiny:
        title.append(t.tinted(t.pixel_icon("sparkles", color="#FFFFFF", tooltip=tr('raid_seed.shiny_039a0a', 'Shiny')), crystal_colors(context)))
    mark = SIZE_MARKS.get(boss["scale"])
    if mark:
        title.append(t.tinted(t.pixel_icon(f"{mark.lower()}-mark", color="#FFFFFF", tooltip=translate(f"{mark} mark")),
                              crystal_colors(context)))
    title.append(stars_row(stars, context))
    accent = t.RED if context["content"] in ("black", "might") else t.BLUE
    facts = ft.Row([
        t.chip(tr('raid_seed.level_6095a3', 'Level {value0}', value0=boss['level']), "sword", accent),
        t.chip(tr('raid_seed.tera_1d43ce', '{value0} Tera', value0=TERA_TYPES[boss['tera_type_original']]), "diamond-gem", accent),
        t.chip(NATURES[boss["nature"]]), t.chip(GENDERS[boss["gender"]]),
        # The compact card keeps to one row: its title's icons tell these.
        *([t.chip(tr('raid_seed.shiny_039a0a', 'Shiny'), "sparkles", accent)] if shiny and not compact else []),
        *([t.chip(translate(f"{mark} mark"), f"{mark.lower()}-mark", accent)] if mark and not compact else []),
    ], spacing=6, run_spacing=6, wrap=True)
    where = (tr('raid_seed._c00a83', '{value0} · {value1} · {value2} · {value3}', value0=VERSIONS[context['version']], value1=REGIONS[context['map_name']], value2=dict(PROGRESS)[context['progress']], value3=CRYSTALS[context['content']])
             + (tr('raid_seed._940234', ' · {value0}', value0=translate(context['den'])) if context.get("den") else ""))
    ivs = ft.Row([iv_tile(label, iv, stat, compact)
                  for label, iv, stat in zip(STATS, boss["ivs"], boss["stats"])], spacing=6, wrap=True)
    column = [ft.Row(title, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER), facts, ivs]
    if compact:
        column.append(ft.Row([t.text(f"{seed:08X}", 11, t.SOFT, font_family=t.MONO, selectable=True),
                              t.text(where, 11, t.FAINT)], spacing=10, wrap=True))
    else:
        column.append(ft.Row([t.pixel_icon("map-pin", size=12, color=t.FAINT), t.text(where, 12, t.MUTED)],
                             spacing=6))
    row = [framed_sprite(app, boss["species"], shiny, MINI if compact else SIZE, context),
           ft.Column(column, spacing=8 if compact else 10, expand=True)]
    if on_use:
        row.append(t.secondary_button(tr('raid_seed.use_c36d81', 'Use'), lambda _e: on_use(seed, context), "check"))
    body = ft.Row(row, spacing=14 if compact else 18, vertical_alignment=ft.CrossAxisAlignment.START)
    parts = [body]
    for icon, title, control in (("gift", tr('raid_seed.the_raid_s_own_rewards_6a2d49', "The raid's own rewards"), rewards), ("zap", tr('raid_seed.scripted_actions_c9bea2', 'Scripted actions'), actions)):
        if control is not None:
            parts += [ft.Container(height=1, bgcolor=t.DIVIDER),
                      ft.Row([t.pixel_icon(icon, size=12, color=t.MUTED),
                              t.text(title, 12, t.MUTED, weight=ft.FontWeight.W_600)], spacing=6),
                      control]
    if len(parts) > 1:
        body = ft.Column(parts, spacing=10, tight=True)
    return ft.Container(body, padding=12 if compact else 16, border_radius=14,
                        border=ft.Border.all(1, ft.Colors.with_opacity(0.08, "#FFFFFF")),
                        gradient=ft.LinearGradient(begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT,
                                                   colors=[ft.Colors.with_opacity(0.08, accent), t.FIELD],
                                                   stops=[0, 0.55]))


class RaidSeedPicker:
    """The seed, what it gives in the tool's raid context, and Find a raid."""

    def __init__(self, app, value: str, on_change, context, on_context_change):
        self.app, self.on_change = app, on_change
        self.context, self.on_context_change = context, on_context_change
        self.seed = t.field(value=str(value or ""), mono=True, expand=True, on_change=self._typed)
        self.preview = ft.Container()
        self.control = ft.Column([
            ft.Row([self.seed, t.secondary_button(tr('raid_seed.find_a_raid_493258', 'Find a raid'), self._open, "search")], spacing=8),
            self.preview], spacing=8, tight=True)
        self._show(str(value or ""), update=False)

    def _show(self, text: str, update: bool = True) -> None:
        seed = seed_of(text)
        self.seed.error = None if seed is not None else tr('raid_seed.eight_hexadecimal_digits_e0e5af', 'Eight hexadecimal digits.')
        self.preview.content = None
        if seed is not None:
            context = self.context()
            try:
                raid = raid_search.generate(seed, context)
            except ValueError as exc:       # an event this context cannot spawn
                self.seed.error, raid = error_message(exc), None
            if raid is not None:
                boss = translate(raid_encounter.tables()["species_names"][str(raid.species)])
                rewards = ft.Container(reward_chips(None, raid.rewards))
                actions = ft.Container(action_rows(None, boss, raid.actions))
                self.preview.content = boss_card(self.app, seed, raid.stars, raid.boss,
                                                 {**context, **raid.context}, rewards=rewards, actions=actions)
                threading.Thread(target=self._name, args=(raid, boss, rewards, actions), daemon=True).start()
        if update:
            self.control.update()

    def _name(self, raid, boss, rewards, actions) -> None:
        """Names the rewards and the moves of the scripted actions."""
        def names(kind):
            try:
                return {n["id"]: n["name"] for n in SERVICE.names("sv", kind)}
            except Exception:
                return {}
        rewards.content = reward_chips(names("bag"), raid.rewards)
        actions.content = action_rows(names("moves"), boss, raid.actions)
        self.app.ui(lambda: (self._update(rewards), self._update(actions)))

    @staticmethod
    def _update(control) -> None:
        try:
            control.update()
        except RuntimeError:        # the card was redrawn while the names loaded
            pass

    def _typed(self, event) -> None:
        event.control.value = event.control.value.upper()
        self.on_change(event.control.value)
        self._show(event.control.value)

    def _use(self, seed: int, context: dict) -> None:
        self.app.page.pop_dialog()
        self.seed.value = f"{seed:08X}"
        self.on_change(self.seed.value)
        self.on_context_change(context)

    def _open(self, _event) -> None:
        current = self.context()
        event = current.get("event")
        pick = lambda control: None if control.value in (None, "any", "-", "") else control.value

        def reward_scope():
            """-> the contexts searched and the boss filters that narrow the rewards listed."""
            scope = raid_search.contexts(version.value, region.value, story.value, crystal.value,
                                         event=event, group=crystal.value)
            if not scope:
                raise ValueError(tr('raid_seed.no_den_of_the_event_spawns_in_that_game_at_that_progres_a94b84', 'No den of the event spawns in that game at that progress.'))
            return scope, dict(stars=pick(stars) and int(stars.value),
                               species_id=pick(species) and int(species.value),
                               tera_type=pick(tera) and int(tera.value))
        wants = RewardFilter(self.app, reward_scope)

        def changed() -> None:
            wants.changed()
            if event is not None:
                size_marks()
        choose = lambda options, value: t.dropdown(options, value, on_select=lambda _e: changed())
        if event is None:
            version = choose([("any", tr('raid_seed.any_game_44475d', 'Any game')), ("scarlet", tr('raid_seed.scarlet_f11da0', 'Scarlet')), ("violet", tr('raid_seed.violet_2a3642', 'Violet'))],
                             current["version"])
            region = choose([("any", tr('raid_seed.any_region_16c11a', 'Any region')), ("paldea", tr('raid_seed.paldea_14c1fa', 'Paldea')), ("kitakami", tr('raid_seed.kitakami_44ab29', 'Kitakami')),
                             ("blueberry", tr('raid_seed.blueberry_d20244', 'Blueberry'))], current["map_name"])
            story = choose([("any", tr('raid_seed.any_progress_92dec4', 'Any progress')), *PROGRESS], current["progress"])
            crystal = choose([("any", tr('raid_seed.any_crystal_9030c8', 'Any crystal')), ("standard", tr('raid_seed.standard_ef6691', 'Standard')), ("black", tr('raid_seed.black_c6cfe6', 'Black'))], "any")
            star_levels = range(1, 7)
        else:
            # Only what the event spawns: its games, Paldea, its dens and the progresses they draw at.
            games = raid_event.versions(event)
            version = choose(([("any", tr('raid_seed.any_game_44475d', 'Any game'))] if len(games) > 1 else [])
                             + [(v, VERSIONS[v]) for v in games], current["version"])
            region = choose([("paldea", tr('raid_seed.paldea_14c1fa', 'Paldea'))], "paldea")
            region.disabled = True
            dens = raid_event.dens(event)
            stages = {p for v in games for d in raid_event.dens(event, v)
                      for p in raid_event.progresses(event, v, d.group)}
            story = choose([("any", tr('raid_seed.any_progress_92dec4', 'Any progress')),
                            *((key, label) for key, label in PROGRESS if key in stages)], current["progress"])
            crystal = choose(([("any", tr('raid_seed.any_den_110e59', 'Any den'))] if len(dens) > 1 else [])
                             + [(str(d.group), translate(d.label)) for d in dens], str(current["group"]))
            star_levels = sorted({s for d in dens for s in d.stars})
        species = NamePicker(self.app, "sv", "species", "", lambda _v: changed(),
                             names=[{"id": s, "name": translate(n)} for s, n in raid_search.species(event)]).control
        stars = choose([("any", tr('raid_seed.any_stars_c3a446', 'Any stars')), *((str(n), tr('raid_seed.stars_0dc50f', '{value0} stars', value0=n)) for n in star_levels)], "any")
        tera = choose([("any", tr('raid_seed.any_tera_type_b8f9f7', 'Any Tera type')), *((str(i), n) for i, n in enumerate(TERA_TYPES))], "any")
        nature = choose([("any", tr('raid_seed.any_nature_c9ac32', 'Any nature')), *((str(i), n) for i, n in enumerate(NATURES))], "any")
        gender = choose([("any", tr('raid_seed.any_gender_28721e', 'Any gender')), *((str(i), n) for i, n in enumerate(GENDERS))], "any")
        shiny = choose([("any", tr('raid_seed.shiny_or_not_678cc0', 'Shiny or not')), ("yes", tr('raid_seed.shiny_only_789bf3', 'Shiny only')), ("no", tr('raid_seed.not_shiny_834dca', 'Not shiny'))], "any")
        size_mark = choose([("any", tr('raid_seed.eligible_or_not_e56066', 'Eligible or not')), ("either", tr('raid_seed.any_mark_42f0cd', 'Any mark')), ("mini", tr('raid_seed.mini_mark_5e0e3e', 'Mini mark')),
                            ("jumbo", tr('raid_seed.jumbo_mark_7d50a4', 'Jumbo mark'))], "any")

        def size_marks(update: bool = True) -> None:
            """An event's band or own scale can rule a mark out: its option is greyed out, and picked, it
            falls back to Eligible or not."""
            try:
                scope, narrow = reward_scope()
                able = raid_search.size_marks(scope, stars=narrow["stars"], species_id=narrow["species_id"])
            except ValueError:
                able = set(raid_search.SIZE_MARKS)
            for option in size_mark.options:
                option.disabled = option.key != "any" and option.key not in able
            if size_mark.value not in able:
                size_mark.value = "any"
            if update:
                size_mark.update()
        if event is not None:
            size_marks(update=False)
        rank = choose([(key, translate(label)) for key, (label, _, _) in raid_search.OBJECTIVES.items()], "overall")
        ivs = [t.field(hint=tr('raid_seed.any_d6a7cd', 'any'), mono=True, expand=True, text_align=ft.TextAlign.CENTER,
                       content_padding=ft.Padding(4, 8, 4, 8)) for _ in STATS]
        start = t.field(value=self.seed.value if seed_of(self.seed.value) is not None else "00000000",
                        mono=True, expand=True)

        count = t.field(value=str(raid_search.DEFAULT_COUNT), mono=True, keyboard_type=ft.KeyboardType.NUMBER)
        shuffle = t.icon_button("shuffle", None, tr('raid_seed.start_at_a_random_seed_7553d1', 'Start at a random seed'))

        def randomize(_e):
            start.value = f"{random.getrandbits(32):08X}"
            start.update()
        shuffle.on_click = randomize

        def everything(on: bool) -> None:
            """Every seed: the first seed and the count step aside, and the search covers all of them."""
            for control in (start, count, shuffle):
                control.disabled = on
                control.update()
        every = Check(tr('raid_seed.every_seed_all_1216aa', 'Every seed, all {value0:,}', value0=ALL_SEEDS), tr('raid_seed.search_every_seed_of_each_game_region_progress_and_crys_09d240', 'Search every seed of each game, region, progress and crystal chosen'), everything)
        first_only = Check(tr('raid_seed.stop_at_the_first_match_feb0b5', 'Stop at the first match'), tr('raid_seed.answer_the_first_raid_that_matches_whatever_its_score_t_e2bfd8', 'Answer the first raid that matches, whatever its score: the earliest seed of the first game, region, progress and crystal that has one'))
        results = ft.ListView(spacing=8, expand=True)
        results.controls = [empty_results()]
        status = t.text(tr('raid_seed.choose_what_the_raid_should_be_then_search_369fd1', 'Choose what the raid should be, then Search.'), 12, t.MUTED)
        busy = ft.Container(PixelActivity(tr('raid_seed.searching_03bd6f', 'Searching')), visible=False)
        # How far the search is: moving until the first seeds are counted, then the share searched.
        bar = ft.ProgressBar(value=None, color=t.BLUE, bgcolor=t.FIELD, height=4, border_radius=2, visible=False)
        run = t.button(tr('raid_seed.search_49c266', 'Search'), None, "search")
        stop = t.secondary_button(tr('raid_seed.stop_cae7d5', 'Stop'), None)
        stop.disabled = True
        cancel, closed = threading.Event(), threading.Event()

        def close(_=None):
            cancel.set()
            closed.set()
            self.app.page.pop_dialog()

        def done(found, stopped):
            if closed.is_set():
                return
            results.controls = [boss_card(self.app, f.seed, f.stars, f.boss, f.context, compact=True,
                                          rewards=reward_chips(wants.names, f.rewards) if f.rewards else None,
                                          on_use=self._use) for f in found] or [empty_results(True)]
            status.value = (tr('raid_seed._54ef3b', '{value0} {value1}', value0=len(found), value1=tr('raid_seed.raid_263dae', 'raid') if len(found) == 1 else tr('raid_seed.raids_b73466', 'raids'))
                            + (tr('raid_seed.before_the_search_stopped_152892', ' before the search stopped.') if stopped else ".") if found else tr('raid_seed.no_raid_matches_27ced5', 'No raid matches.'))
            run.disabled, stop.disabled, busy.visible, bar.visible = False, True, False, False
            for control in (results, status, run, stop, busy, bar):
                control.update()

        def submit(_):
            try:
                scope = raid_search.contexts(version.value, region.value, story.value, crystal.value,
                                             event=event, group=crystal.value)
                if not scope:
                    raise ValueError(tr('raid_seed.no_den_of_the_event_spawns_in_that_game_at_that_progres_a94b84', 'No den of the event spawns in that game at that progress.'))
                if every.value:              # offered with the helper alone, which takes every seed
                    first, amount = 0, ALL_SEEDS
                else:
                    first = seed_of(start.value)
                    amount = int(count.value) if count.value.strip().isdigit() else 0
                    most = raid_search.most_seeds(len(scope))
                    if first is None or not 1 <= amount <= most:
                        raise ValueError(tr('raid_seed.start_at_an_eight_digit_seed_and_search_up_to_seeds_725440', 'Start at an eight-digit seed and search up to {value0:,} seeds', value0=most)
                                         + (tr('raid_seed.in_this_scope_20cead', ' in this scope.') if most < ALL_SEEDS else "."))
                ranges = tuple(iv_range(field.value) for field in ivs)
                filters = dict(stars=pick(stars) and int(stars.value),
                               species_id=pick(species) and int(species.value),
                               tera_type=pick(tera) and int(tera.value),
                               nature=pick(nature) and int(nature.value),
                               gender=pick(gender) and int(gender.value),
                               shiny=None if pick(shiny) is None else shiny.value == "yes",
                               size_mark=pick(size_mark),
                               ivs=None if ranges == ((0, 31),) * 6 else ranges,
                               rewards=wants.wanted())
                if rank.value == "rewards" and not filters["rewards"]:
                    raise ValueError(tr('raid_seed.most_desired_rewards_ranks_by_the_wanted_rewards_open_r_a0bf6d', 'Most desired rewards ranks by the wanted rewards: open Rewards and add one.'))
            except ValueError as exc:
                status.value, status.color = error_message(exc), t.RED
                status.update()
                return
            cancel.clear()
            status.value, status.color = tr('raid_seed.searching_78c9d9', 'Searching...'), t.MUTED
            results.controls, run.disabled, stop.disabled, busy.visible = [], True, False, True
            bar.value, bar.visible = None, True
            for control in (status, results, run, stop, busy, bar):
                control.update()

            began = time.monotonic()

            def progress(done_count, total):
                status.value = searching(done_count, total, time.monotonic() - began)
                bar.value = done_count / total if total else None
                self.app.ui(lambda: (self._update(status), self._update(bar)))

            def work():
                try:
                    found = raid_search.search(first, amount, scope, rank.value,
                                               one_per_species=filters["species_id"] is None, limit=30,
                                               progress=progress, cancelled=cancel.is_set,
                                               stop_at_first=first_only.value, **filters)
                    self.app.ui(lambda: done(found, cancel.is_set()))
                except Exception as exc:
                    message = error_message(exc)

                    def failed():
                        if not closed.is_set():
                            status.value, status.color, run.disabled = message, t.RED, False
                            stop.disabled, busy.visible, bar.visible = True, False, False
                            for control in (status, run, stop, busy, bar):
                                control.update()
                    self.app.ui(failed)
            threading.Thread(target=work, daemon=True).start()

        run.on_click = submit
        stop.on_click = lambda _e: cancel.set()
        pair = lambda *controls: ft.Row(list(controls), spacing=8)
        filters = ft.Column([
            heading("map-pin", tr('raid_seed.where_the_raid_is_a53f82', 'Where the raid is')),
            pair(t.labeled_control(tr('raid_seed.game_5c412a', 'Game'), version, expand=True), t.labeled_control(tr('raid_seed.region_d3a008', 'Region'), region, expand=True)),
            pair(t.labeled_control(tr('raid_seed.story_progress_d527c5', 'Story progress'), story, expand=True),
                 t.labeled_control(tr('raid_seed.crystal_b8c18c', 'Crystal'), crystal, expand=True)),
            heading("sword", tr('raid_seed.the_boss_e384fe', 'The boss')),
            pair(t.labeled_control(tr('raid_seed.species_56205e', 'Species'), species, expand=True), t.labeled_control(tr('raid_seed.stars_4e44da', 'Stars'), stars, expand=True)),
            pair(t.labeled_control(tr('raid_seed.tera_type_bbaed3', 'Tera type'), tera, expand=True), t.labeled_control(tr('raid_seed.nature_c71ce8', 'Nature'), nature, expand=True)),
            pair(t.labeled_control(tr('raid_seed.gender_a04630', 'Gender'), gender, expand=True), t.labeled_control(tr('raid_seed.shiny_039a0a', 'Shiny'), shiny, expand=True)),
            pair(t.labeled_control(tr('raid_seed.size_mark_eligibility_3d3da2', 'Size mark eligibility'), size_mark, expand=True), ft.Container(expand=True)),
            heading("sliders-horizontal", tr('raid_seed.ivs_39e3d6', 'IVs')),
            pair(*(t.labeled_control(label, field, expand=True) for label, field in zip(STATS, ivs))),
            t.text(tr('raid_seed.blank_for_any_a_value_or_a_range_such_as_20_31_bdf130', 'Blank for any, a value, or a range such as 20-31.'), 11, t.FAINT),
            wants.control,
            heading("search", tr('raid_seed.search_49c266', 'Search')),
            t.labeled_control(tr('raid_seed.rank_by_a66d85', 'Rank by'), rank),
            t.text(tr('raid_seed.bulk_and_offense_estimate_how_hard_the_boss_is_from_its_bf190b', 'Bulk and offense estimate how hard the boss is from its stats alone. Most desired rewards ranks by the wanted rewards, the first row first.'), 11, t.FAINT),
            pair(t.labeled_control(tr('raid_seed.first_seed_608b7d', 'First seed'), ft.Row([start, shuffle], spacing=4,
                                                         vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                   expand=True),
                 t.labeled_control(tr('raid_seed.seeds_to_search_ecf3d1', 'Seeds to search'), count, expand=True)),
            *([every.control] if raid_search.FAST else []),
            first_only.control,
        ], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True)
        found = ft.Column([
            ft.Column([ft.Row([busy, status], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER), bar],
                      spacing=6, tight=True),
            t.fade(results)], spacing=10, expand=True)
        self.app.page.show_dialog(t.dialog(
            title=t.text(tr('raid_seed.find_a_tera_raid_bfa708', 'Find a Tera Raid'), 17, weight=ft.FontWeight.W_600),
            content=ft.Container(ft.Row([
                ft.Container(t.fade(filters), width=360, padding=ft.Padding(0, 0, 12, 0)),
                ft.Container(width=1, bgcolor=t.DIVIDER),
                ft.Container(found, expand=True, padding=ft.Padding(8, 0, 0, 0)),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.STRETCH), width=1000, height=600),
            actions=[t.secondary_button(tr('raid_seed.close_7d9eb7', 'Close'), close), stop, run]))


def heading(icon: str, title: str) -> ft.Container:
    return ft.Container(ft.Row([t.pixel_icon(icon, size=12, color=t.BLUE),
                                t.text(title, 12, t.SOFT, weight=ft.FontWeight.W_600)], spacing=8),
                        padding=ft.Padding(0, 6, 0, 0))


def empty_results(searched: bool = False) -> ft.Container:
    return ft.Container(ft.Column([
        t.tinted(t.pixel_icon("diamond-gem", size=48, color="#FFFFFF"), t.BRAND_BLUE),
        t.text(tr('raid_seed.no_raid_matches_widen_a_filter_or_search_more_seeds_f6f3f7', 'No raid matches. Widen a filter or search more seeds.') if searched else
               tr('raid_seed.the_raids_the_search_finds_appear_here_cb237f', 'The raids the search finds appear here.'), 13, t.MUTED, text_align=ft.TextAlign.CENTER),
    ], spacing=12, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        alignment=ft.Alignment.CENTER, padding=ft.Padding(0, 120, 0, 0))
