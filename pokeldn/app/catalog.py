"""What the app offers per game: each tool is an entry point, the tested flags it always gets, the
fields a user fills in, and what to press on the console. Fixed arguments may carry {received}
(the Received folder), {stamp} (the run's time), {src_var} (a fresh random id) and {keys} (the
prod.keys file Settings names)."""
from pokeldn.app.i18n import ref as _ref
from pokeldn.app import preview
from pokeldn.app.i18n import message_ref as tr, ref, join as join_text
from dataclasses import dataclass, replace

from pokeldn.sv.circle import BP_MAX
from pokeldn.sv.raid import REWARD_ROWS
from pokeldn.swsh.raid import REWARD_SLOTS as SWSH_REWARD_ROWS
from pokeldn.swsh import lair as swsh_lair


@dataclass(frozen=True)
class Field:
    flag: str | tuple[str, ...]   # "" is positional; a tuple passes the same value to each flag, but
                                  # raidpartners's tuple is its picks' flag then its progress's
    label: str
    kind: str = "text"            # text number choice switch pokemon file builder multi linkcode code
                                  # (eight digits) raidseed lairseed rewards raidevent raidden raidpartners
                                  # raideventboss (one value per flag, colon-separated) encounter, or a
                                  # PKHeX name list: species move item ball
    help: str = ""
    default: str | bool = ""
    choices: tuple[tuple[str, str], ...] = ()
    required: bool = False
    group: str = ""               # fields sharing a group render on one card
    invert: bool = False          # a switch that passes its flag when turned off
    unset: tuple[str, ...] = ()   # arguments passed when the field is left empty
    exts: tuple[str, ...] = ()
    when: tuple[str, str] = ()    # (flag, value): the field applies only while that field has that value
    unless: str = ""             # hide and omit the field while this source field has a value
    requires: str = ""           # hide and omit the field while this source field has no value
    template: str = ""            # the value is passed as template.format(value), e.g. "ball={}"
    limits: tuple[tuple[str, int, str], ...] = ()   # (NAME, highest, why) for NAME=VALUE text
    choice_help: tuple[tuple[str, str], ...] = ()
    queue: int = 1                # a pokemon field: how many trades one session can carry
    more: str = ""                # a pokemon field: the flag for the second and later offers
    count: str = ""               # a pokemon field: the flag that carries how many there are
    hidden: bool = False          # applied with its default, set on the Advanced tab instead of Basic
    shiny: bool = False           # a switch that makes the species field's Pokemon shiny, for its sprite
    events: bool = False          # a pokemon field picked among the game's Mystery Gift Pokemon, not built
    your_ot: bool = False         # a switch for a gift that names its receiver: off and disabled while
                                  # the one chosen has its own trainer (command.locked)
    length: int = 8               # a code field's digits
    remembered: bool = True       # False: the value starts empty at every launch, as a Union
                                  # Circle's Link Code, new each time
    bounds: tuple[int, int] = ()  # a number field's lowest and highest value

    identity: str = ""         # stable key for a translated positional field

    @property
    def key(self) -> str:
        if isinstance(self.flag, tuple):
            return self.flag[0]
        if self.template:
            return f"{self.flag} {self.template}"
        return self.flag or self.identity or f"#{self.label}"


@dataclass(frozen=True)
class Tool:
    key: str
    name: str
    script: str
    summary: str
    steps: tuple[str | tuple[str, tuple[str, str]], ...]   # a (step, (flag, value)) shows only while
                                                            # that field has that value
    fields: tuple[Field, ...] = ()
    fixed: tuple[str, ...] = ()
    doc: str = ""
    unavailable: str = ""         # why the tool cannot run yet; it is shown greyed out


@dataclass(frozen=True)
class Game:
    key: str
    name: str
    short: str
    doc: str
    tools: tuple[Tool, ...]
    icon: str = ""                # an image file; empty: the app's games/<key>.png


VERSIONS = (("firered", ref('core.catalog.firered_7d9d1b')), ("leafgreen", ref('core.catalog.leafgreen_578f94')))
LANGUAGES = (("english", ref('core.catalog.english_ba118b')), ("french", ref('core.catalog.french_745819')), ("german", ref('core.catalog.german_a659b6')),
             ("italian", ref('core.catalog.italian_fe1d9c')), ("spanish", ref('core.catalog.spanish_341105')), ("japanese", ref('core.catalog.japanese_be4ee9')))
CHANNELS = (("1", "1"), ("6", "6"), ("11", "11"))


def _swsh_lair_legendaries():
    import json
    from pathlib import Path
    names = json.loads((Path(swsh_lair.__file__).with_name("data") / "species.json").read_text())["species_names"]
    return tuple((str(n), names.get(str(n), f"#{n}")) for n in swsh_lair.legendaries())


SWSH_LAIR_LEGENDARIES = _swsh_lair_legendaries()
FRESH_PID = Field("--fresh-pid", ref('core.catalog.new_pid_each_run_a6f96e'), "switch", default=True, hidden=True,
                  help=ref('core.catalog.offer_the_pokemon_under_a_new_pid_and_encryption_consta_4e58db'))
FOR_RECEIVER = Field("--for-receiver", ref('core.catalog.made_for_the_receiving_player_1dfdde'), "switch", default=True, hidden=True,
                     your_ot=True,
                     help=ref('core.catalog.a_gift_that_gave_its_receiver_s_own_trainer_is_made_aga_3ec345'))
GIFT_OFFER_BACK = (ref('core.catalog.offer_a_pokemon_you_caught_in_this_save_and_confirm_the_abaf36'))
CHANNEL_HELP = ref('core.catalog.the_wireless_channel_of_the_network_pokeldn_hosts_101d44')
CODE_HELP = ref('core.catalog.the_same_code_the_player_enters_on_the_console_c91cb8')


def host_seconds(default: str, extra: str = "") -> Field:
    return Field("--seconds", tr('core.catalog.time_limit_seconds_cf9965'), "number", default=default, hidden=True,
                 help=join_text((p for p in (tr('core.catalog.how_long_the_host_stays_up_after_start_then_it_closes_o_64465a'), extra) if p), " "))


def join_seconds(default: str) -> Field:
    return Field("--hold", tr('core.catalog.time_limit_seconds_cf9965'), "number", default=default, hidden=True,
                 help=tr('core.catalog.how_long_the_joiner_stays_connected_once_it_joins_the_c_4b4161'))


QUEUE = 6   # a party's worth


def offer(flag: str = "", required: bool = True, help: str = "", queue: int = 1, more: str = "",
          count: str = "") -> Field:
    return Field(flag, tr('core.catalog.pokemon_to_offer_585ae1'), "pokemon", required=required,
                 help=help or tr('core.catalog.pick_a_species_pkhex_builds_a_legal_one_for_this_game_a135d7'),
                 queue=queue, more=more, count=count, identity="#Pokemon to offer")


def queued(flag: str = "", help: str = "", **kw) -> Field:
    """An offer field whose session trades each entry in turn, on one seat."""
    help = help or tr('core.catalog.pick_a_species_pkhex_builds_a_legal_one_for_this_game_a135d7')
    return offer(flag, help=tr('core.catalog.add_a_trade_to_queue_more_one_session_trades_them_in_or_4b4782', value0=help),
                 queue=QUEUE, **kw)


ONLINE_CODE_HELP = (ref('core.catalog.eight_digits_you_and_your_partner_agree_on_you_also_ent_363a9f'))


def without(fixed: tuple[str, ...], flag: str) -> tuple[str, ...]:
    """`fixed` with `flag` and its value taken out."""
    out, skip = [], False
    for arg in fixed:
        if skip:
            skip = False
        elif arg == flag:
            skip = True
        else:
            out.append(arg)
    return tuple(out)


def online(host: Tool, steps: tuple[str, ...], code: Field) -> Tool:
    """The host tool trading a partner far away instead of a built offer (docs/online.md). `code`
    is the room both players enter, the console's own link code where the game has one."""
    kept = tuple(f for f in host.fields if f.kind != "pokemon" and f is not FRESH_PID
                 and f.flag not in ("--seconds", code.flag))
    return Tool(host.key.replace("-host", "-online"), tr('core.catalog.trade_online_857839'), host.script,
                tr('core.catalog.trade_with_a_player_far_away_each_of_you_hosts_your_own_a2baeb'),
                (tr('core.catalog.agree_on_a_code_with_your_partner_or_leave_it_empty_to__ad0df6'),
                 tr('core.catalog.start_then_wait_for_trading_with_and_your_partner_s_nam_ca9884'), *steps,
                 tr('core.catalog.your_partner_s_pokemon_appears_once_they_offer_it_the_t_4a8d28')),
                (code,) + kept + ((host_seconds("1800", tr('core.catalog.leave_time_to_find_a_partner_and_trade_aba8cd')),)
                                  if any(f.flag == "--seconds" for f in host.fields)
                                  or "--seconds" in host.fixed else ()),
                fixed=without(host.fixed, "--seconds") + ("--online",), doc="online.md")


FRLG_PATH = ref('core.catalog.pokemon_center_2f_third_attendant_direct_corner_trade_c_2e7181')

FRLG = Game("frlg", ref('core.catalog.firered_leafgreen_2b757f'), ref('core.catalog.frlg_ec6db6'), "frlg.md", (
    Tool("frlg-trade-host", ref('core.catalog.trade_host_7198bc'), "bin/frlg_trade_host.py",
         ref('core.catalog.host_a_direct_corner_trade_the_console_joins_pokeldn_s__b51633'),
         (ref('core.catalog.start_the_host_and_wait_for_hosting_direct_corner_in_th_02ea3b'),
          tr('core.catalog.join_group_then_pick_pokeldn_125fa7', value0=FRLG_PATH),
          ref('core.catalog.choose_the_pokemon_to_trade_and_confirm_f140d0'),
          ref('core.catalog.with_several_queued_trade_again_after_each_save_the_hos_f49450'),
          ref('core.catalog.back_on_the_trade_menu_after_the_last_save_wait_for_the_5e2aa1')),
         (queued(count="--trades"),
          Field("--version", ref('core.catalog.version_dd1679'), "choice", default="firered", choices=VERSIONS, group=ref('core.catalog.console_29a408'),
                help=ref('core.catalog.the_game_pokeldn_s_own_trainer_reports_on_the_link_and__ced820')),
          Field("--language", ref('core.catalog.trainer_language_bca3f4'), "choice", default="english", choices=LANGUAGES, hidden=True,
                help=ref('core.catalog.the_language_pokeldn_s_own_trainer_reports_on_the_link_5ac75b')),
          Field("--channel", ref('core.catalog.channel_ce4683'), "choice", default="11", choices=CHANNELS, help=CHANNEL_HELP, hidden=True)),
         fixed=("--live", "--phy", 'auto', "--slot", "0", "--ot", "{ot}", "--id", "{tid}:{sid}",
                "--out", "{received}/frlg-{stamp}.pk3"),
         doc="frlg_link.md"),
    Tool("frlg-trade-join", ref('core.catalog.trade_join_8cec7d'), "bin/frlg_trade_join.py",
         ref('core.catalog.join_a_trade_group_the_console_leads_a29709'),
         (ref('core.catalog.start_the_joiner_first_it_scans_until_the_console_appea_c11e9c'),
          tr('core.catalog.become_leader_6fc7ff', value0=FRLG_PATH),
          ref('core.catalog.accept_pokeldn_when_it_appears_then_choose_and_confirm_785998'),
          ref('core.catalog.with_several_queued_trade_again_after_each_save_the_joi_54215e')),
         (queued(count="--trades"),),
         fixed=("--live", "--phy", 'auto', "--slot", "0", "--ot", "{ot}", "--id", "{tid}:{sid}",
                "--out", "{received}/frlg-{stamp}.pk3"),
         doc="frlg_link.md"),
    Tool("frlg-gift", ref('core.catalog.mystery_gift_68b50f'), "bin/frlg_mg_host.py",
         ref('core.catalog.send_pokemon_items_or_game_boosts_back_up_or_restore_yo_d6ff78'),
         (ref('core.catalog.title_screen_mystery_gift_wonder_cards_friend_for_news__4fd567'),
          ref('core.catalog.start_the_host_then_pick_pokeldn_when_it_appears_abee9d'),
          ref('core.catalog.answer_yes_if_the_console_asks_to_replace_its_card_95ef96'),
          ref('core.catalog.for_boosts_save_backups_and_restores_readouts_or_your_o_8646b9'),
          ref('core.catalog.back_out_of_the_search_screen_between_two_runs_f0a1d7')),
         (Field(("--version", "--expect-console"), ref('core.catalog.version_dd1679'), "choice", default="firered",
                choices=VERSIONS, group=ref('core.catalog.console_29a408'),
                help=ref('core.catalog.the_console_s_cartridge_another_one_is_refused_before_a_7a71c8')),
          Field("--gift-file", ref('core.catalog.gift_1a596a'), "builder"),
          Field("--language", ref('core.catalog.trainer_language_bca3f4'), "choice", default="english", choices=LANGUAGES, hidden=True,
                help=ref('core.catalog.the_language_pokeldn_s_own_trainer_reports_on_the_link_5ac75b')),
          Field("--channel", ref('core.catalog.channel_ce4683'), "choice", default="11", choices=CHANNELS, help=CHANNEL_HELP, hidden=True)),
         fixed=("--live", "--ot", "{ot}", "--id", "{tid}:{sid}", "--dump-file",
                "{received}/frlg-dump-{stamp}.bin"), doc="frlg_gift.md"),
))

RSE_VERSIONS = (("emerald", ref('core.catalog.emerald')), ("ruby", ref('core.catalog.ruby')),
                ("sapphire", ref('core.catalog.sapphire')))


def rse_tool(tool: Tool) -> Tool:
    """A FireRed and LeafGreen tool for a Ruby, Sapphire or Emerald console: the same launcher, the
    same Pokemon Center 2F attendants [pokeemerald data/maps/*_PokemonCenter_2F], other versions."""
    # Ruby and Sapphire have no Mystery Gift menu, only the e-Reader's Mystery Event.
    versions = RSE_VERSIONS[:1] if tool.key == "frlg-gift" else RSE_VERSIONS
    fields = tuple(replace(f, choices=versions, default="emerald") if f.choices == VERSIONS else f
                   for f in tool.fields)
    if tool.key == "frlg-gift":
        tool = replace(tool, summary=tr('core.catalog.rse_gift_summary'), steps=(
            tr('core.catalog.rse_gift_menu'),
            tr('core.catalog.start_the_host_then_pick_pokeldn_when_it_appears_abee9d'),
            tr('core.catalog.answer_yes_if_the_console_asks_to_replace_its_card_95ef96'),
            tr('core.catalog.rse_gift_delivery'),
            tr('core.catalog.back_out_of_the_search_screen_between_two_runs_f0a1d7')))
    return replace(tool, key=tool.key.replace("frlg-", "rse-"), fields=fields, doc="rse.md",
                   fixed=tuple(a.replace("/frlg-", "/rse-") for a in tool.fixed))


# Unreleased on the Switch: shown only while pokeldn.app.preview is enabled (docs/rse.md).
RSE = Game("rse", ref('core.catalog.rse_name'), ref('core.catalog.rse_short'), "rse.md",
           tuple(rse_tool(tool) for tool in FRLG.tools))

LGPE_STEPS = ref('core.catalog.x_communicate_local_communication_trade_enter_the_same__d54e70')

LGPE = Game("lgpe", ref('core.catalog.let_s_go_pikachu_eevee_188f2e'), ref('core.catalog.lgpe_26db3d'), "lgpe.md", (
    Tool("lgpe-host", ref('core.catalog.trade_host_7198bc'), "bin/lgpe_host.py",
         ref('core.catalog.host_a_trade_under_a_link_code_the_console_joins_bf0e81'),
         (ref('core.catalog.start_the_host_first_40ac31'), LGPE_STEPS, ref('core.catalog.choose_a_pokemon_and_confirm_8215d8')),
         (queued("--offer", more="--next-offer"),
          Field("--code", ref('core.catalog.link_code_0b8f86'), "linkcode", required=True,
                help=ref('core.catalog.the_three_pokemon_the_player_picks_on_the_console_in_th_174ead')),
          FRESH_PID,
          host_seconds("1200", ref('core.catalog.a_trade_under_way_when_it_runs_out_is_finished_first_5f61a0'))),
         fixed=("--first", "echo", "--trainer-name", "{ot}", "--our-trainer", "{tid}:{sid}",
                "--received", "{received}/lgpe-{stamp}.pb7"), doc="lgpe.md"),
    Tool("lgpe-join", ref('core.catalog.trade_join_8cec7d'), "bin/lgpe_join.py",
         ref('core.catalog.join_the_console_s_trade_search_2e2f10'),
         (ref('core.catalog.start_the_joiner_it_scans_for_up_to_five_minutes_9d2ad3'), LGPE_STEPS,
          ref('core.catalog.offer_and_confirm_once_pokeldn_shows_queued_pokemon_fol_dec462')),
         (queued("--offer"), FRESH_PID),
         fixed=("--channels", "1,6,11", "--dwell", "2.5", "--connect", "--connect-seconds", "1800",
                "--ack-peer-clock", "--ack-re-announce", "--facts", "lgpe_net_facts.json",
                "--trainer-name", "{ot}", "--our-trainer", "{tid}:{sid}",
                "--received", "{received}/lgpe-{stamp}.pb7"),
         doc="lgpe_session.md"),
))

SWSH = Game("swsh", ref('core.catalog.sword_shield_71b23d'), ref('core.catalog.swsh_dc0b3b'), "swsh.md", (
    Tool("swsh-host", ref('core.catalog.trade_host_7198bc'), "bin/swsh_host.py", ref('core.catalog.host_a_link_trade_the_console_joins_9250f7'),
         (ref('core.catalog.start_the_host_and_wait_for_the_network_to_come_up_6d8341'),
          ref('core.catalog.y_comm_link_trade_local_communication_press_a_on_both_m_19fa15'),
          ref('core.catalog.choose_a_pokemon_and_confirm_when_pokeldn_appears_c5c28c'),
          ref('core.catalog.queued_pokemon_follow_one_per_trade_pick_again_from_the_06fa29')),
         (queued("--offer-file"), FRESH_PID,
          Field("--code", ref('core.catalog.link_code_cc04a1'), "code", help=ref('core.catalog.eight_digits_empty_for_a_plain_trade_adde63')),
          Field("--channel", ref('core.catalog.channel_ce4683'), "choice", default="6", choices=CHANNELS, help=CHANNEL_HELP, hidden=True),
          host_seconds("900")),
         fixed=("--player-name", "{ot}", "--trainer-name", "{ot}",
                "--trainer-tid", "{tid}", "--trainer-sid", "{sid}",
                "--received", "{received}/swsh-{stamp}.pk8"), doc="swsh_trade.md"),
    Tool("swsh-join", ref('core.catalog.trade_join_8cec7d'), "bin/swsh_connect.py", ref('core.catalog.join_the_console_s_link_trade_search_52ee13'),
         (ref('core.catalog.y_comm_link_trade_local_communication_no_code_press_a_o_db5138'),
          ref('core.catalog.start_the_joiner_while_the_console_searches_5f19a9'),
          ref('core.catalog.pokeldn_appears_on_the_trade_screen_choose_a_pokemon_an_18ef79'),
          ref('core.catalog.queued_pokemon_follow_one_per_trade_pick_again_from_the_06fa29')),
         (queued("--offer-file", required=False,
                 help=ref('core.catalog.pick_a_species_pkhex_builds_a_legal_one_empty_offers_yo_899d7f')),
          FRESH_PID,
          join_seconds("900")),
         fixed=("--preset", 'trade', "--send-snapshot", "live",
                "--snapshot-name", "{ot}", "--snapshot-tid", "{tid}", "--snapshot-sid", "{sid}",
                "--save-offered", "{received}/swsh-{stamp}.pk8"),
         doc="swsh_trade.md"),
    Tool("swsh-gift", ref('core.catalog.mystery_gift_68b50f'), "bin/swsh_gift_host.py",
         ref('core.catalog.send_a_local_wireless_gift_choose_a_preset_an_official__e32c41'),
         (ref('core.catalog.mystery_gift_receive_a_gift_via_local_wireless_0c1758'),
          ref('core.catalog.start_the_host_the_card_is_listed_within_a_few_seconds__8fbdcc'),
          ref('core.catalog.accept_the_card_then_stop_the_host_e08246')),
         (Field("--gift-file", ref('core.catalog.gift_1a596a'), "builder"),
          Field("--seconds", ref('core.catalog.time_limit_seconds_cf9965'), "number", default="300", hidden=True,
                help=ref('core.catalog.how_long_the_card_is_advertised_after_start_0dba41'))),
         doc="swsh_gift.md"),
    Tool("swsh-raid-host", ref('core.catalog.max_raid_host_5d0e1a'), "bin/swsh_host.py",
         ref('core.catalog.host_a_max_raid_the_console_joins_you_choose_the_boss_i_7c2f41'),
         (ref('core.catalog.choose_the_boss_the_pokemon_our_player_brings_and_if_yo_3b8e90'),
          ref('core.catalog.start_the_host_9b26a9'),
          ref('core.catalog.y_comm_in_local_wireless_mode_join_pokeldn_s_raid_from__a91d47'),
          ref('core.catalog.press_ready_the_console_runs_the_battle_and_our_pokemon_6f02b3'),
          ref('core.catalog.win_the_raid_to_receive_the_rewards_dcd72e')),
         (Field("--raid-event", ref('core.catalog.raid_event_d4b4e5'), "raidevent",
                help=ref('core.catalog.a_boss_from_a_past_wild_area_event_from_project_pokemon_3e1f70')),
          Field(("--raid-version", "--raid-stars", "--raid-event-boss", "--raid-area"), ref('core.catalog.event_boss_6b2a9d'),
                "raideventboss", requires="--raid-event",
                help=ref('core.catalog.the_event_s_bosses_a_den_can_show_with_their_stars_leve_0c58e2')),
          Field("--raid-boss", ref('core.catalog.boss_8f6c1d'), "pokemon", required=True, unless="--raid-event",
                help=ref('core.catalog.the_raid_s_boss_a_boss_a_den_can_hold_shows_in_every_co_e2a7b9')),
          Field("--raid-gigantamax", ref('core.catalog.gigantamax_boss_0a7e52'), "switch", unless="--raid-event",
                help=ref('core.catalog.for_a_pokemon_a_den_holds_as_gigantamax_charizard_snorl_6b1d40')),
          Field("--offer-file", ref('core.catalog.our_pokemon_14a66b'), "pokemon", required=True,
                help=ref('core.catalog.the_pokemon_our_player_brings_pkhex_checks_it_is_legal_abc1cf')),
          Field("--raid-reward", ref('core.catalog.rewards_59afe4'), "rewards",
                help=tr('core.catalog.leave_empty_for_the_den_s_own_rewards_or_choose_up_to_va_91e2d4', value0=SWSH_REWARD_ROWS)),
          Field("--channel", ref('core.catalog.channel_ce4683'), "choice", default="6", choices=CHANNELS, help=CHANNEL_HELP, hidden=True),
          host_seconds("900")),
         fixed=("--raid-console-serves", "--player-name", "{ot}", "--trainer-name", "{ot}",
                "--trainer-tid", "{tid}", "--trainer-sid", "{sid}"), doc="swsh_raid.md"),
    Tool("swsh-lair-raid-host", ref('core.catalog.dynamax_adventure_host_4c81e2'), "bin/swsh_host.py",
         ref('core.catalog.host_a_dynamax_adventure_the_console_joins_you_choose_t_9a3f17'),
         (ref('core.catalog.choose_the_legendary_then_start_the_host_5be0c4'),
          ref('core.catalog.at_the_max_lair_talk_to_the_receptionist_press_to_set_t_8d4b19'),
          ref('core.catalog.press_ready_once_pokeldn_is_in_the_lobby_80d6b3'),
          ref('core.catalog.pokeldn_leaves_once_the_adventure_starts_a_computer_par_2c7f05')),
         (Field("--lair-legendary", ref('core.catalog.legendary_6e94a1'), "choice", default="150",
                choices=SWSH_LAIR_LEGENDARIES,
                help=ref('core.catalog.the_legendary_pokemon_waiting_at_the_end_of_the_max_lai_b0d3e8')),
          Field("--code", ref('core.catalog.link_code_cc04a1'), "code",
                help=ref('core.catalog.eight_digits_the_console_sets_with_at_the_receptionist__5a8e30')),
          Field("--lair-seed", ref('core.catalog.adventure_seed_1f7c55'), "lairseed", template="0x{}",
                help=ref('core.catalog.sets_the_rental_pokemon_and_the_pokemon_met_on_the_way_e4b8d2')),
          Field("--channel", ref('core.catalog.channel_ce4683'), "choice", default="6", choices=CHANNELS, help=CHANNEL_HELP, hidden=True),
          host_seconds("600")),
         fixed=("--player-name", "{ot}", "--trainer-name", "{ot}",
                "--trainer-tid", "{tid}", "--trainer-sid", "{sid}"), doc="swsh_raid.md"),
))

BDSP_ROOM = ref('core.catalog.pokemon_center_2f_left_attendant_plain_yes_no_password__35cfcc')

BDSP = Game("bdsp", ref('core.catalog.brilliant_diamond_shining_pearl_f30922'), ref('core.catalog.bdsp_1358ba'), "bdsp.md", (
    Tool("bdsp-host", ref('core.catalog.trade_host_7198bc'), "bin/bdsp_host.py",
         ref('core.catalog.host_a_union_room_the_console_enters_d169f8'),
         (ref('core.catalog.start_the_host_before_the_player_enters_the_room_c8c655'),
          tr('core.catalog.our_character_appears_4daa86', value0=BDSP_ROOM),
          ref('core.catalog.y_communicate_trade_pokemon_accept_the_greeting_then_ch_068c66')),
         (queued("--offer"),
          FRESH_PID,
          Field("--password", ref('core.catalog.room_password_158a0a'), "code", help=ref('core.catalog.eight_digits_empty_for_the_plain_room_235b0d')),
          host_seconds("1500")),
         fixed=("--ldn-protocol", "1", "--complete-trade", "--save-theirs", "{received}/bdsp-{stamp}",
                "--language", "{language}", "--name", "{ot}", "--trainer", "{ot}:{tid}:{sid}"),
         doc="bdsp_trade.md"),
    Tool("bdsp-join", ref('core.catalog.trade_join_8cec7d'), "bin/bdsp_connect.py",
         ref('core.catalog.join_the_console_s_union_room_as_a_character_and_trade_e07848'),
         (tr('core.catalog.wait_in_the_room_clear_of_the_walls_c546ae', value0=BDSP_ROOM),
          ref('core.catalog.start_the_joiner_and_wait_for_the_character_to_appear_afaf82'),
          ref('core.catalog.y_communicate_trade_pokemon_and_wait_the_greeting_comes_ae79bc'),
          ref('core.catalog.between_runs_leave_and_re_enter_the_room_b1e71c')),
         (queued("--trade-template"),
          Field("--trade-nickname", ref('core.catalog.nickname_d720f6'), hidden=True,
                help=ref('core.catalog.a_nickname_given_to_every_offered_pokemon_empty_keeps_t_c4aaf8')),
          FRESH_PID,
          join_seconds("600")),
         fixed=("--channels", "1,6,11", "--count", "9", "--connect", "5", "--join", "6",
                "--reliable-ack", "--reliable-sweep", "3", "--room-walk", "15", "--room-pattern", "fixed",
                "--room-walk-steps", "0", "--join-avatar", "0", "--answer-requests", "--state", "0",
                "--recruiting", "0", "--answer-talk", "--can-talk", "0", "--initiate-talk",
                "--initiate-delay", "3", "--after-approach", "0x06:0001000000", "--trade-reply",
                "--complete-trade", "--src-var", "{src_var}",
                "--trade-save-poke", "{received}/bdsp-{stamp}.pb8", "--language", "{language}",
                "--name", "{ot}", "--trade-name", "{ot}", "--trade-tid", "{tid}", "--trade-sid", "{sid}"),
         doc="bdsp_trade.md"),
))

PLA_STEPS = (ref('core.catalog.talk_to_the_trade_npc_in_jubilife_village_trade_local_p_63341c'),
             ref('core.catalog.enter_the_same_eight_digit_code_and_press_to_search_2d0ec5'))
PLA_OFFER_HELP = ref('core.catalog.pick_a_species_pkhex_builds_a_legal_one_empty_offers_po_304364')

PLA = Game("pla", ref('core.catalog.legends_arceus_260415'), ref('core.catalog.pla_eafc6b'), "pla.md", (
    Tool("pla-host", ref('core.catalog.trade_host_7198bc'), "bin/pla_host.py",
         ref('core.catalog.host_a_trade_under_a_link_code_the_console_joins_bf0e81'),
         (ref('core.catalog.start_the_host_first_40ac31'), *PLA_STEPS, ref('core.catalog.offer_a_pokemon_and_confirm_ae970b'),
          ref('core.catalog.leave_the_host_running_until_the_trade_ends_an_interrup_adc091')),
         (queued("--trade-box-record", required=False, help=PLA_OFFER_HELP),
          Field("--code", ref('core.catalog.link_code_0b8f86'), "code", default="00000000", help=CODE_HELP),
          FRESH_PID,
          host_seconds("900")),
         fixed=("--channel", "6", "--session-update", "--sustain", "--clock", "--data-exchange",
                "--game-channel", "--trade-box", "--player-name", "{ot}", "--gender", "{gender}",
                "--offer-out", "{received}/pla-{stamp}.pa8"),
         doc="pla.md"),
    Tool("pla-join", ref('core.catalog.trade_join_8cec7d'), "bin/pla_join.py",
         ref('core.catalog.find_your_console_s_trade_search_and_connect_automatica_388352'),
         (*PLA_STEPS, ref('core.catalog.start_the_joiner_84b994'), ref('core.catalog.offer_and_confirm_once_the_partner_shows_b0b40e')),
         (queued("--offer", required=False, help=PLA_OFFER_HELP),
          Field("--code", ref('core.catalog.link_code_0b8f86'), "code", default="00000000", help=CODE_HELP),
          FRESH_PID),
         fixed=("--player-name", "{ot}", "--gender", "{gender}",
                "--offer-out", "{received}/pla-{stamp}.pa8"),
         doc="pla.md"),
))

SV_SEARCH = ref('core.catalog.x_poke_portal_link_trade_offline_then_search_634a34')

SV = Game("sv", ref('core.catalog.scarlet_violet_504657'), ref('core.catalog.sv_a4cd8b'), "sv.md", (
    Tool("sv-host", ref('core.catalog.trade_host_7198bc'), "bin/sv_host.py",
         ref('core.catalog.host_a_trade_the_searching_console_joins_d5a11b'),
         (ref('core.catalog.start_the_host_first_40ac31'), SV_SEARCH, ref('core.catalog.offer_and_confirm_on_the_trade_screen_7d393b')),
         (queued("--trade-offer"),
          Field("--code", ref('core.catalog.link_code_cc04a1'), "code", help=ref('core.catalog.empty_hosts_a_search_with_no_code_6d9fdd'),
                unset=("--game-data",
                       "000000000000000000000000000000000000000000000000000000000000000000648cf400000000")),
          FRESH_PID),
         fixed=("--channel", "6", "--seconds", "900", "--host-player-id", "00000000000000010000000000000000",
                "--player-name", 'POKELDN', "--rtt-probe", "--net-property", "--clock", "--net-stations", "4",
                "--scarlet-response", "--join-seq", "0", "--update-first-seq", "0", "--update-seq", "1",
                "--session-flags", "0x00", "--no-session-ack", "--update-delay", "2.03",
                "--host-player-name", " ", "--record-delay", "0.17",
                "--send-at", "0.06:0x7c:1:b90104b902b9027b0001b902b902320201b902b902320101b902b902320301",
                "--send-at", "0.06:0x81:1:0000000000f38800000000",
                "--send-at", "0.04:0x81:5:000500000ff00800000000",
                "--announce", "--announce-delay", "5.25",
                "--send-at", "6.00:0x7c:1:b90101b902b90280800001", "--offer-after-open", "2",
                "--trainer-name", "{ot}", "--offer-out", "{received}/sv-{stamp}.pk9"),
         doc="sv.md"),
    Tool("sv-join", ref('core.catalog.trade_join_8cec7d'), "bin/sv_join.py",
         ref('core.catalog.join_the_console_s_link_trade_search_52ee13'),
         (SV_SEARCH, ref('core.catalog.start_the_joiner_84b994'), ref('core.catalog.offer_and_confirm_on_the_trade_screen_7d393b'),
          ref('core.catalog.if_the_console_keeps_refusing_leave_and_re_enter_the_se_28b562')),
         (queued("--trade-offer"),
          Field("--code", ref('core.catalog.link_code_cc04a1'), "code", help=ref('core.catalog.empty_joins_a_search_with_no_code_caae9d')),
          FRESH_PID),
         fixed=("--phy", 'auto', "--seconds", "1500", "--hold", "900", "--channels", "1,6,11",
                "--dwell", "0.4", "--connect-timeout", "6", "--open-delay", "0.3", "--record-delay", "0.3",
                "--session-join", "--answer-migration", "--net-ack", "--ack-flags", "0x00",
                "--game-channel", "--announce-timeout", "20", "--rtt-delay", "0.3",
                "--trainer-name", "{ot}", "--offer-out", "{received}/sv-{stamp}.pk9"), doc="sv.md"),
    Tool("sv-raid-host", ref('core.catalog.tera_raid_host_d3c097'), "bin/sv_host.py",
         ref('core.catalog.host_a_tera_raid_the_console_joins_you_choose_the_raid__ba0395'),
         (ref('core.catalog.choose_the_pokemon_our_player_brings_the_raid_and_if_yo_c1ebd8'),
          ref('core.catalog.start_the_host_9b26a9'),
          ref('core.catalog.on_each_console_x_poke_portal_tera_raid_battle_search_o_3b317a'),
          ref('core.catalog.press_ready_on_each_console_the_raid_starts_once_every__8c975c'),
          ref('core.catalog.our_player_leaves_when_the_battle_starts_its_pokemon_st_284730'),
          ref('core.catalog.a_communication_error_may_show_as_the_battle_starts_dis_fd7b88'),
          ref('core.catalog.win_the_raid_to_receive_the_rewards_dcd72e')),
         (Field("--raid-pokemon", ref('core.catalog.our_pokemon_14a66b'), "pokemon", required=True,
                help=ref('core.catalog.the_pokemon_our_player_brings_pkhex_checks_it_is_legal_abc1cf')),
          Field("--raid-event", ref('core.catalog.raid_event_d4b4e5'), "raidevent",
                help=ref('core.catalog.a_raid_from_a_past_poke_portal_news_event_from_project__17be6a')),
          Field("--raid-version", ref('core.catalog.game_5c412a'), "choice", default='violet', group=ref('core.catalog.the_raid_a6f6bf'),
                choices=((_ref('core.pokeldn.app.catalog.scarlet_f763ca7a'), ref('core.catalog.scarlet_f11da0')), (_ref('core.pokeldn.app.catalog.violet_22d2084f'), ref('core.catalog.violet_2a3642'))),
                help=ref('core.catalog.a_seed_can_give_another_raid_in_the_other_version_bf545f')),
          Field("--raid-map", ref('core.catalog.region_d3a008'), "choice", default='paldea', group=ref('core.catalog.the_raid_a6f6bf'),
                choices=((_ref('core.pokeldn.app.catalog.paldea_f1ba8838'), ref('core.catalog.paldea_14c1fa')), (_ref('core.pokeldn.app.catalog.kitakami_7676c1fa'), ref('core.catalog.kitakami_44ab29')), (_ref('core.pokeldn.app.catalog.blueberry_ab45e847'), ref('core.catalog.blueberry_d20244')))),
          Field("--raid-progress", ref('core.catalog.story_progress_d527c5'), "choice", default='4star', group=ref('core.catalog.the_raid_a6f6bf'),
                choices=((_ref('core.pokeldn.app.catalog.beginning_4095391c'), ref('core.catalog.beginning_9e6b41')), (_ref('core.pokeldn.app.catalog.tera_b28dca38'), ref('core.catalog.tera_raids_unlocked_07d442')),
                         (_ref('core.pokeldn.app.catalog.3star_400dbed9'), ref('core.catalog.3_star_raids_e72615')), (_ref('core.pokeldn.app.catalog.4star_f04fd401'), ref('core.catalog.4_star_raids_d82c77')),
                         (_ref('core.pokeldn.app.catalog.5star_7d1be078'), ref('core.catalog.5_star_raids_d693f5')), (_ref('core.pokeldn.app.catalog.6star_bb06f4ea'), ref('core.catalog.6_star_raids_e7e30a'))),
                help=ref('core.catalog.sets_how_many_stars_a_standard_crystal_can_have_fb17ea')),
          Field("--raid-content", ref('core.catalog.crystal_b8c18c'), "choice", default='standard', group=ref('core.catalog.the_raid_a6f6bf'),
                choices=((_ref('core.pokeldn.app.catalog.standard_fe6d3468'), ref('core.catalog.standard_ef6691')), (_ref('core.pokeldn.app.catalog.black_c006c7e3'), ref('core.catalog.black_6_stars_3ee5de'))), unless="--raid-event"),
          Field("--raid-event-group", ref('core.catalog.crystal_b8c18c'), "raidden", group=ref('core.catalog.the_raid_a6f6bf'), requires="--raid-event",
                help=ref('core.catalog.each_of_the_event_s_crystals_has_its_own_bosses_628ee4')),
          Field("--raid-seed", ref('core.catalog.raid_seed_e70045'), "raidseed", default="000F34C3", required=True,
                group=ref('core.catalog.the_raid_a6f6bf'), help=ref('core.catalog.eight_hexadecimal_digits_find_a_raid_searches_seeds_for_b8aa2b')),
          Field("--raid-reward", ref('core.catalog.rewards_59afe4'), "rewards",
                help=tr('core.catalog.leave_empty_for_the_raid_s_own_rewards_or_list_up_to_it_6e5d73', value0=REWARD_ROWS)),
          Field("--raid-players", ref('core.catalog.consoles_joining_7a43ed'), "choice", default="1",
                choices=(("1", ref('core.catalog.1_console_90b18a')), ("2", ref('core.catalog.2_consoles_5e36d3')), ("3", ref('core.catalog.3_consoles_af51df'))),
                help=ref('core.catalog.the_raid_waits_for_this_many_consoles_each_one_ready_be_60226a')),
          Field(("--raid-partner", "--raid-partner-progress"), ref('core.catalog.raid_npc_partners_c62ef4'), "raidpartners",
                help=ref('core.catalog.the_trainers_who_fill_the_slots_no_console_holds_two_wi_906d17')),
          Field("--raid-catch-normal", ref('core.catalog.catch_an_event_boss_again_f24ceb'), "switch", hidden=True,
                requires="--raid-event",
                help=ref('core.catalog.offer_a_boss_the_event_lets_a_save_catch_once_as_a_norm_0ebdc3')),
          host_seconds("600")),
         fixed=("--channel", "1", "--scene-id", "7", "--max-participants", "4", "--code", "4970",
                "--scarlet-response", "--session-flags", "0", "--session-packet-id", "1",
                "--no-session-ack", "--join-seq", "0", "--update-seq", "0", "--update-delay", "0.02",
                "--rtt-probe", "--clock", "--net-stations", "4", "--record-delay", "0.1",
                "--record-spacing", "0.003", "--host-player-id", "00000000000000010000000000000000",
                "--host-player-name", "{ot}", "--trainer-name", "{ot}"),
         doc="sv_raid.md"),
    Tool("sv-raid-join", ref('core.catalog.tera_raid_join_75d587'), "bin/sv_join.py",
         ref('core.catalog.join_a_tera_raid_the_console_hosts_and_leave_one_of_you_b6a64d'),
         (ref('core.catalog.on_the_console_a_tera_raid_crystal_challenge_as_a_group_d752cd'),
          ref('core.catalog.choose_the_pokemon_our_player_brings_then_start_the_joi_571094'),
          ref('core.catalog.our_player_joins_and_readies_start_the_battle_on_the_co_edacf9'),
          ref('core.catalog.our_player_leaves_as_the_battle_starts_its_pokemon_figh_421b73')),
         (Field("--raid-pokemon", ref('core.catalog.our_pokemon_14a66b'), "pokemon", required=True,
                help=ref('core.catalog.the_pokemon_our_player_brings_pkhex_checks_it_is_legal_abc1cf')),
          join_seconds("240")),
         fixed=("--seconds", "900", "--name", 'POKELDN', "--trainer-name", "{ot}"),
         doc="sv_raid.md"),
    Tool("sv-circle-join", ref('core.catalog.union_circle_quests_6ec3ee'), "bin/sv_join.py",
         ref('core.catalog.join_the_union_circle_the_console_hosts_and_clear_blueb_a7f910'),
         (ref('core.catalog.on_the_console_x_poke_portal_union_circle_then_start_a__28de4e'),
          ref('core.catalog.enter_the_same_link_code_here_choose_the_task_and_start_0dffcf'),
          (ref('core.catalog.once_pokeldn_is_in_the_group_start_the_circle_on_the_co_0d4e89'),
           ("--circle-task", "snacksworth")),
          (ref('core.catalog.once_pokeldn_is_in_the_group_start_the_circle_on_the_co_7a9a17'),
           ("--circle-task", "bp")),
          ref('core.catalog.close_the_bp_side_bar_on_the_console_to_see_the_bp_come_bd0b25'),
          (ref('core.catalog.for_snacksworth_talk_to_him_once_for_each_legendary_eac_87f6c8'),
           ("--circle-task", "snacksworth"))),
         (Field("--code", ref('core.catalog.link_code_cc04a1'), "code", required=True, length=4,
                remembered=False,
                help=ref('core.catalog.the_union_circle_s_four_digit_link_code_2e76dc')),
          Field("--circle-task", ref('core.catalog.task_4bc74b'), "choice", default="snacksworth",
                choices=(("snacksworth", ref('core.catalog.unlock_all_remaining_snacksworth_legendaries_cd6e98')),
                         ("bp", ref('core.catalog.give_bp_b0e117'))),
                choice_help=(("snacksworth", ref('core.catalog.reads_how_many_solo_and_team_quests_the_host_still_lack_55eb31')),
                             ("bp", ref('core.catalog.clears_one_quest_for_the_host_that_pays_this_bp_2c54b4')))),
          Field("--bbq-clear", ref('core.catalog.bp_36b717'), "number", default="1000", required=True,
                when=("--circle-task", "bp"), bounds=(1, BP_MAX),
                help=ref('core.catalog.from_1_to_9_999_999_the_most_bp_a_player_holds_99d199')),
          join_seconds("900")),
         fixed=("--union-circle", "--seconds", "900", "--name", 'POKELDN', "--trainer-name", "{ot}"),
         doc="sv_union_circle.md"),
    Tool("sv-circle-encounters-join", ref('core.catalog.union_circle_encounters_31663b'), "bin/sv_join.py",
         ref('core.catalog.join_the_union_circle_the_console_hosts_and_spawn_the_w_88db74'),
         (ref('core.catalog.on_the_console_x_poke_portal_union_circle_then_start_a__28de4e'),
          ref('core.catalog.enter_the_same_link_code_here_craft_the_pokemon_and_sta_23247e'),
          ref('core.catalog.once_pokeldn_is_in_the_group_start_the_circle_on_the_co_c34ac9'),
          ref('core.catalog.three_of_the_pokemon_come_15_to_25_m_around_you_one_you_47e6f7'),
          ref('core.catalog.with_legal_encounters_only_they_wait_until_the_wild_pok_aca8b5'),
          ref('core.catalog.close_the_circle_on_the_console_to_stop_fa751d')),
         (Field("--code", ref('core.catalog.link_code_cc04a1'), "code", required=True, length=4,
                remembered=False,
                help=ref('core.catalog.the_union_circle_s_four_digit_link_code_2e76dc')),
          Field("--spawn", ref('core.catalog.pokemon_to_spawn_c7ecd1'), "encounter", required=True,
                help=ref('core.catalog.the_wild_pokemon_that_appears_around_you_in_the_game_to_c2e57e')),
          join_seconds("3600")),
         fixed=("--union-circle", "--seconds", "3600", "--follow-host", "--name", 'POKELDN',
                "--trainer-name", "{ot}"),
         doc="sv_union_circle.md"),
))

ZA = Game("za", ref('core.catalog.legends_z_a_594c26'), ref('core.catalog.plza_bc9316'), "za.md", (
    Tool("za-host", ref('core.catalog.trade_host_7198bc'), "bin/za_host.py",
         ref('core.catalog.host_a_trade_the_searching_console_joins_d5a11b'),
         (ref('core.catalog.start_the_host_first_40ac31'),
          ref('core.catalog.x_link_play_link_trade_nearby_players_the_same_code_the_b0f613'),
          ref('core.catalog.pick_on_the_trade_box_offer_then_trade_queued_pokemon_f_5554fc'),
          ref('core.catalog.back_out_with_b_after_the_last_trade_97a1dc')),
         (queued("--trade-offer"),
          Field("--code", ref('core.catalog.link_code_0b8f86'), "code", default="00000000", help=CODE_HELP),
          FRESH_PID,
          host_seconds("900")),
         fixed=("--trainer-name", "{ot}", "--offer-out", "{received}/za-{stamp}.pa9"), doc="za.md"),
    Tool("za-join", ref('core.catalog.trade_join_8cec7d'), "bin/za_join.py",
         ref('core.catalog.join_the_console_s_link_trade_search_52ee13'),
         (ref('core.catalog.link_trade_local_communication_search_with_the_link_cod_4e7c15'),
          ref('core.catalog.start_the_joiner_refusals_while_seating_are_normal_let__2e1cb1'),
          ref('core.catalog.pick_on_the_trade_box_and_confirm_once_pokeldn_appears__693ece')),
         (queued("--trade-offer"),
          Field("--code", ref('core.catalog.link_code_0b8f86'), "code", default="00000000", help=CODE_HELP),
          FRESH_PID),
         fixed=("--channels", "1,6,11", "--dwell", "0.35", "--seconds", "1200", "--hold", "900",
                "--quiet-seat", "25", "--connect-timeout", "6", "--mac", "02:11:32:54:76:98", "--game",
                "--offer-delay", "4", "--trainer-name", "{ot}", "--offer-out", "{received}/za-{stamp}.pa9"),
         doc="za.md"),
))

def simulated_gift(game: Game, host: Tool, steps: tuple[str, ...]) -> Tool:
    """The trade host offering up to a party's worth of the game's Mystery Gift Pokemon, picked from PKHeX's
    event table, in place of built ones and made for the receiving player where each card names them
    (docs/gift_simulated.md)."""
    def gift(f: Field) -> tuple[Field, ...]:
        if f.kind != "pokemon":
            return f,
        return (replace(f, identity="#Mystery Gift Pokemon" if not f.flag else f.identity, label=tr('core.catalog.mystery_gift_pokemon_e3340b'), required=True, events=True, queue=QUEUE,
                        help=tr('core.catalog.every_pokemon_gift_gave_from_pkhex_s_event_database_add_cbef41', value0=game.name, value1=QUEUE)),
                FOR_RECEIVER)
    return Tool(host.key.replace("-host", "-gift-host"), tr('core.catalog.mystery_gift_simulated_d9d548'), host.script,
                tr('core.catalog.trade_an_official_mystery_gift_pokemon_to_the_console_a_a079f5'), steps, tuple(g for f in host.fields for g in gift(f)), fixed=host.fixed,
                doc="gift_simulated.md")


def trade_keys(game: Game) -> tuple[str, str]:
    """The keys of `game`'s trade host and joiner."""
    if any(t.key == f"{game.key}-trade-host" for t in game.tools):
        return f"{game.key}-trade-host", f"{game.key}-trade-join"
    return f"{game.key}-host", f"{game.key}-join"


def with_gift(game: Game, steps: tuple[str, ...]) -> Game:
    """`game` with its Mystery Gift - Simulated after its trades, made from its trade host."""
    host = next(t for t in game.tools if t.key == trade_keys(game)[0])
    at = max(n for n, t in enumerate(game.tools) if t.key in trade_keys(game)) + 1
    return replace(game, tools=game.tools[:at] + (simulated_gift(game, host, steps),) + game.tools[at:])


def with_online(game: Game, steps: tuple[str, ...], code: Field | None = None) -> Game:
    """`game` with its online trade after its local trades; `code` replaces the host's own code field's
    help, or is a new field where the game has no code."""
    host = next(t for t in game.tools if t.key == trade_keys(game)[0])
    if code is None:
        code = next(f for f in host.fields if f.kind in ("code", "linkcode"))
        code = replace(code, help=ONLINE_CODE_HELP if code.kind == "code" else
                       tr('core.catalog.the_three_pokemon_you_and_your_partner_pick_in_the_same_a31f1a'))
    at = max(n for n, t in enumerate(game.tools) if t.key in trade_keys(game)) + 1   # after Join
    return replace(game, tools=game.tools[:at] + (online(host, steps, code),) + game.tools[at:])


GAMES = (
    with_online(FRLG, (tr('core.catalog.join_group_then_pick_pokeldn_125fa7', value0=FRLG_PATH),
                       ref('core.catalog.your_partner_s_party_shows_on_the_right_choose_the_poke_ca7e7b')),
                Field("--online-code", ref('core.catalog.code_340f46'), "code", help=ONLINE_CODE_HELP)),
    with_online(with_gift(LGPE, (ref('core.catalog.choose_the_event_pokemon_then_start_the_host_51919d'), LGPE_STEPS, GIFT_OFFER_BACK)),
                (LGPE_STEPS, ref('core.catalog.choose_a_pokemon_and_confirm_8215d8'))),
    with_online(SWSH, (ref('core.catalog.y_comm_link_trade_local_communication_with_the_same_lin_316b85'),
                       ref('core.catalog.choose_the_pokemon_to_send_when_pokeldn_appears_bb19f5'))),
    with_online(with_gift(BDSP, (ref('core.catalog.choose_the_event_pokemon_then_start_the_host_before_the_2416a8'), tr('core.catalog.our_character_appears_4daa86', value0=BDSP_ROOM),
                                 ref('core.catalog.y_communicate_trade_pokemon_accept_the_greeting_bc6aa6'), GIFT_OFFER_BACK)),
                (tr('core.catalog.our_character_appears_4daa86', value0=BDSP_ROOM),
                 ref('core.catalog.y_communicate_trade_pokemon_accept_the_greeting_then_ch_2c7215')),
                Field("--password", ref('core.catalog.code_340f46'), "code", help=ref('core.catalog.eight_digits_you_and_your_partner_agree_on_you_also_ent_a2a06f'))),
    with_online(with_gift(PLA, (ref('core.catalog.choose_the_event_pokemon_then_start_the_host_51919d'), *PLA_STEPS, GIFT_OFFER_BACK,
                                ref('core.catalog.leave_the_host_running_until_the_trade_ends_an_interrup_adc091'))),
                (*PLA_STEPS, ref('core.catalog.offer_a_pokemon_and_confirm_ae970b'))),
    with_online(with_gift(SV, (ref('core.catalog.choose_the_event_pokemon_then_start_the_host_51919d'), SV_SEARCH, GIFT_OFFER_BACK)),
                (SV_SEARCH, ref('core.catalog.offer_and_confirm_on_the_trade_screen_7d393b'))),
    with_online(with_gift(ZA, (ref('core.catalog.choose_the_event_pokemon_then_start_the_host_51919d'),
                               ref('core.catalog.x_link_play_link_trade_nearby_players_the_same_code_the_b0f613'),
                               ref('core.catalog.pick_a_pokemon_you_caught_in_this_save_on_the_trade_box_855d95'),
                               ref('core.catalog.back_out_with_b_after_the_last_trade_97a1dc'))),
                (ref('core.catalog.x_link_play_link_trade_nearby_players_the_same_code_the_b0f613'),
                 ref('core.catalog.pick_on_the_trade_box_offer_then_trade_b0a22c'))),
)

if preview.enabled():
    GAMES = GAMES[:1] + (with_online(RSE, (tr('core.catalog.join_group_then_pick_pokeldn_125fa7', value0=FRLG_PATH),
                                           ref('core.catalog.your_partner_s_party_shows_on_the_right_choose_the_poke_ca7e7b')),
                                     Field("--online-code", ref('core.catalog.code_340f46'), "code", help=ONLINE_CODE_HELP)),) + GAMES[1:]
