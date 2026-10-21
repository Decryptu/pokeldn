"""What the app offers per game: each tool is an entry point, the tested flags it always gets, the
fields a user fills in, and what to press on the console. Fixed arguments may carry {received}
(the Received folder), {stamp} (the run's time), {src_var} (a fresh random id) and {keys} (the
prod.keys file Settings names)."""
from pokeldn.app import preview
from pokeldn.app.i18n import t as tr
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


VERSIONS = (("firered", tr('catalog.firered_7d9d1b', 'FireRed')), ("leafgreen", tr('catalog.leafgreen_578f94', 'LeafGreen')))
LANGUAGES = (("english", tr('catalog.english_ba118b', 'English')), ("french", tr('catalog.french_745819', 'French')), ("german", tr('catalog.german_a659b6', 'German')),
             ("italian", tr('catalog.italian_fe1d9c', 'Italian')), ("spanish", tr('catalog.spanish_341105', 'Spanish')), ("japanese", tr('catalog.japanese_be4ee9', 'Japanese')))
CHANNELS = (("1", "1"), ("6", "6"), ("11", "11"))


def _swsh_lair_legendaries():
    import json
    from pathlib import Path
    names = json.loads((Path(swsh_lair.__file__).with_name("data") / "species.json").read_text())["species_names"]
    return tuple((str(n), names.get(str(n), f"#{n}")) for n in swsh_lair.legendaries())


SWSH_LAIR_LEGENDARIES = _swsh_lair_legendaries()
FRESH_PID = Field("--fresh-pid", tr('catalog.new_pid_each_run_a6f96e', 'New PID each run'), "switch", default=True, hidden=True,
                  help=tr('catalog.offer_the_pokemon_under_a_new_pid_and_encryption_consta_4e58db', 'Offer the Pokemon under a new PID and encryption constant, so a save that already received it takes it again. Turn it off for a file whose PID must stay, such as an event Pokemon.'))
FOR_RECEIVER = Field("--for-receiver", tr('catalog.made_for_the_receiving_player_1dfdde', 'Made for the receiving player'), "switch", default=True, hidden=True,
                     your_ot=True,
                     help=tr('catalog.a_gift_that_gave_its_receiver_s_own_trainer_is_made_aga_3ec345', "A gift that gave its receiver's own trainer is made again during the trade for the console's save, read from the Pokemon the console offers or from its session data. Off, or when neither names the save, it goes with your trainer from Settings."))
GIFT_OFFER_BACK = (tr('catalog.offer_a_pokemon_you_caught_in_this_save_and_confirm_the_abaf36', 'Offer a Pokemon you caught in this save and confirm. The event Pokemon comes over; yours goes to Received. Trade again for each queued gift, then back out after the last trade.'))
CHANNEL_HELP = tr('catalog.the_wireless_channel_of_the_network_pokeldn_hosts_101d44', 'The wireless channel of the network pokeldn hosts.')
CODE_HELP = tr('catalog.the_same_code_the_player_enters_on_the_console_c91cb8', 'The same code the player enters on the console.')


def host_seconds(default: str, extra: str = "") -> Field:
    return Field("--seconds", tr('catalog.time_limit_seconds_cf9965', 'Time limit (seconds)'), "number", default=default, hidden=True,
                 help=" ".join(p for p in (tr('catalog.how_long_the_host_stays_up_after_start_then_it_closes_o_64465a', 'How long the host stays up after Start, then it closes on its own. Leave time for every trade in the queue.'), extra) if p))


def join_seconds(default: str) -> Field:
    return Field("--hold", tr('catalog.time_limit_seconds_cf9965', 'Time limit (seconds)'), "number", default=default, hidden=True,
                 help=tr('catalog.how_long_the_joiner_stays_connected_once_it_joins_the_c_4b4161', 'How long the joiner stays connected once it joins the console, then it leaves on its own.'))


QUEUE = 6   # a party's worth


def offer(flag: str = "", required: bool = True, help: str = "", queue: int = 1, more: str = "",
          count: str = "") -> Field:
    return Field(flag, tr('catalog.pokemon_to_offer_585ae1', 'Pokemon to offer'), "pokemon", required=required,
                 help=help or tr('catalog.pick_a_species_pkhex_builds_a_legal_one_for_this_game_a135d7', 'Pick a species; PKHeX builds a legal one for this game.'),
                 queue=queue, more=more, count=count, identity="#Pokemon to offer")


def queued(flag: str = "", help: str = "", **kw) -> Field:
    """An offer field whose session trades each entry in turn, on one seat."""
    help = help or tr('catalog.pick_a_species_pkhex_builds_a_legal_one_for_this_game_a135d7', 'Pick a species; PKHeX builds a legal one for this game.')
    return offer(flag, help=tr('catalog.add_a_trade_to_queue_more_one_session_trades_them_in_or_4b4782', '{value0} Add a trade to queue more: one session trades them in order.', value0=help),
                 queue=QUEUE, **kw)


ONLINE_CODE_HELP = (tr('catalog.eight_digits_you_and_your_partner_agree_on_you_also_ent_363a9f', 'Eight digits you and your partner agree on; you also enter them on the console. Empty meets anyone trading this game online without a code.'))


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
    return Tool(host.key.replace("-host", "-online"), tr('catalog.trade_online_857839', 'Trade (Online)'), host.script,
                tr('catalog.trade_with_a_player_far_away_each_of_you_hosts_your_own_a2baeb', 'Trade with a player far away: each of you hosts your own console, and the two trade through the internet.'),
                (tr('catalog.agree_on_a_code_with_your_partner_or_leave_it_empty_to__ad0df6', 'Agree on a code with your partner, or leave it empty to meet anyone trading online.'),
                 tr('catalog.start_then_wait_for_trading_with_and_your_partner_s_nam_ca9884', "Start, then wait for 'Trading with' and your partner's name."), *steps,
                 tr('catalog.your_partner_s_pokemon_appears_once_they_offer_it_the_t_4a8d28', "Your partner's Pokemon appears once they offer it. The trade goes through once both of you confirm.")),
                (code,) + kept + ((host_seconds("1800", tr('catalog.leave_time_to_find_a_partner_and_trade_aba8cd', 'Leave time to find a partner and trade.')),)
                                  if any(f.flag == "--seconds" for f in host.fields)
                                  or "--seconds" in host.fixed else ()),
                fixed=without(host.fixed, "--seconds") + ("--online",), doc="online.md")


FRLG_PATH = tr('catalog.pokemon_center_2f_third_attendant_direct_corner_trade_c_2e7181', 'Pokemon Center 2F, third attendant, Direct Corner, Trade Center')

FRLG = Game("frlg", tr('catalog.firered_leafgreen_2b757f', 'FireRed & LeafGreen'), tr('catalog.frlg_ec6db6', 'FRLG'), "frlg.md", (
    Tool("frlg-trade-host", tr('catalog.trade_host_7198bc', 'Trade (Host)'), "bin/frlg_trade_host.py",
         tr('catalog.host_a_direct_corner_trade_the_console_joins_pokeldn_s__b51633', "Host a Direct Corner trade. The console joins pokeldn's group."),
         (tr('catalog.start_the_host_and_wait_for_hosting_direct_corner_in_th_02ea3b', "Start the host and wait for 'Hosting Direct Corner' in the log."),
          tr('catalog.join_group_then_pick_pokeldn_125fa7', '{value0}, Join Group, then pick POKELDN.', value0=FRLG_PATH),
          tr('catalog.choose_the_pokemon_to_trade_and_confirm_f140d0', 'Choose the Pokemon to trade and confirm.'),
          tr('catalog.with_several_queued_trade_again_after_each_save_the_hos_f49450', 'With several queued, trade again after each save; the host offers the next one.'),
          tr('catalog.back_on_the_trade_menu_after_the_last_save_wait_for_the_5e2aa1', "Back on the trade menu after the last save, wait for the host's prompt, then Cancel and Yes.")),
         (queued(count="--trades"),
          Field("--version", tr('catalog.version_dd1679', 'Version'), "choice", default="firered", choices=VERSIONS, group=tr('catalog.console_29a408', 'Console'),
                help=tr('catalog.the_game_pokeldn_s_own_trainer_reports_on_the_link_and__ced820', "The game pokeldn's own trainer reports on the link, and the one the Pokemon is built for.")),
          Field("--language", tr('catalog.trainer_language_bca3f4', 'Trainer language'), "choice", default="english", choices=LANGUAGES, hidden=True,
                help=tr('catalog.the_language_pokeldn_s_own_trainer_reports_on_the_link_5ac75b', "The language pokeldn's own trainer reports on the link.")),
          Field("--channel", tr('catalog.channel_ce4683', 'Channel'), "choice", default="11", choices=CHANNELS, help=CHANNEL_HELP, hidden=True)),
         fixed=("--live", "--phy", "auto", "--slot", "0", "--ot", "{ot}", "--id", "{tid}:{sid}",
                "--out", "{received}/frlg-{stamp}.pk3"),
         doc="frlg_link.md"),
    Tool("frlg-trade-join", tr('catalog.trade_join_8cec7d', 'Trade (Join)'), "bin/frlg_trade_join.py",
         tr('catalog.join_a_trade_group_the_console_leads_a29709', 'Join a trade group the console leads.'),
         (tr('catalog.start_the_joiner_first_it_scans_until_the_console_appea_c11e9c', 'Start the joiner first: it scans until the console appears.'),
          tr('catalog.become_leader_6fc7ff', '{value0}, Become Leader.', value0=FRLG_PATH),
          tr('catalog.accept_pokeldn_when_it_appears_then_choose_and_confirm_785998', 'Accept POKELDN when it appears, then choose and confirm.'),
          tr('catalog.with_several_queued_trade_again_after_each_save_the_joi_54215e', 'With several queued, trade again after each save; the joiner offers the next one.')),
         (queued(count="--trades"),),
         fixed=("--live", "--phy", "auto", "--slot", "0", "--ot", "{ot}", "--id", "{tid}:{sid}",
                "--out", "{received}/frlg-{stamp}.pk3"),
         doc="frlg_link.md"),
    Tool("frlg-gift", tr('catalog.mystery_gift_68b50f', 'Mystery Gift'), "bin/frlg_mg_host.py",
         tr('catalog.send_pokemon_items_or_game_boosts_back_up_or_restore_yo_d6ff78', 'Send Pokemon, items or game boosts, back up or restore your save, or read your trainer IDs through Mystery Gift.'),
         (tr('catalog.title_screen_mystery_gift_wonder_cards_friend_for_news__4fd567', 'Title screen: Mystery Gift, Wonder Cards, Friend. For news: the second entry, Wonder News.'),
          tr('catalog.start_the_host_then_pick_pokeldn_when_it_appears_abee9d', 'Start the host, then pick POKELDN when it appears.'),
          tr('catalog.answer_yes_if_the_console_asks_to_replace_its_card_95ef96', 'Answer Yes if the console asks to replace its card.'),
          tr('catalog.for_boosts_save_backups_and_restores_readouts_or_your_o_8646b9', 'For boosts, save backups and restores, readouts or your own console code, keep the app running until the Session log shows the result.'),
          tr('catalog.back_out_of_the_search_screen_between_two_runs_f0a1d7', 'Back out of the search screen between two runs.')),
         (Field(("--version", "--expect-console"), tr('catalog.version_dd1679', 'Version'), "choice", default="firered",
                choices=VERSIONS, group=tr('catalog.console_29a408', 'Console'),
                help=tr('catalog.the_console_s_cartridge_another_one_is_refused_before_a_7a71c8', "The console's cartridge: another one is refused before anything is sent.")),
          Field("--gift-file", tr('catalog.gift_1a596a', 'Gift'), "builder"),
          Field("--language", tr('catalog.trainer_language_bca3f4', 'Trainer language'), "choice", default="english", choices=LANGUAGES, hidden=True,
                help=tr('catalog.the_language_pokeldn_s_own_trainer_reports_on_the_link_5ac75b', "The language pokeldn's own trainer reports on the link.")),
          Field("--channel", tr('catalog.channel_ce4683', 'Channel'), "choice", default="11", choices=CHANNELS, help=CHANNEL_HELP, hidden=True)),
         fixed=("--live", "--ot", "{ot}", "--id", "{tid}:{sid}", "--dump-file",
                "{received}/frlg-dump-{stamp}.bin"), doc="frlg_gift.md"),
))

RSE_VERSIONS = (("emerald", tr('catalog.emerald', 'Emerald')), ("ruby", tr('catalog.ruby', 'Ruby')),
                ("sapphire", tr('catalog.sapphire', 'Sapphire')))


def rse_tool(tool: Tool) -> Tool:
    """A FireRed and LeafGreen tool for a Ruby, Sapphire or Emerald console: the same launcher, the
    same Pokemon Center 2F attendants [pokeemerald data/maps/*_PokemonCenter_2F], other versions."""
    # Ruby and Sapphire have no Mystery Gift menu, only the e-Reader's Mystery Event.
    versions = RSE_VERSIONS[:1] if tool.key == "frlg-gift" else RSE_VERSIONS
    fields = tuple(replace(f, choices=versions, default="emerald") if f.choices == VERSIONS else f
                   for f in tool.fields)
    if tool.key == "frlg-gift":
        tool = replace(tool, summary=tr('catalog.rse_gift_summary', 'Send an Emerald Wonder Card through Mystery Gift.'), steps=(
            tr('catalog.rse_gift_menu', 'Title screen: Mystery Gift, Wonder Cards, Friend. Emerald lists Mystery Gift once the player has written LINK TOGETHER WITH ALL on the questionnaire.'),
            tr('catalog.start_the_host_then_pick_pokeldn_when_it_appears_abee9d', 'Start the host, then pick POKELDN when it appears.'),
            tr('catalog.answer_yes_if_the_console_asks_to_replace_its_card_95ef96', 'Answer Yes if the console asks to replace its card.'),
            tr('catalog.rse_gift_delivery', 'After the card is saved, talk to the delivery man on 2F of any Pokemon Center.'),
            tr('catalog.back_out_of_the_search_screen_between_two_runs_f0a1d7', 'Back out of the search screen between two runs.')))
    return replace(tool, key=tool.key.replace("frlg-", "rse-"), fields=fields, doc="rse.md",
                   fixed=tuple(a.replace("/frlg-", "/rse-") for a in tool.fixed))


# Unreleased on the Switch: shown only while pokeldn.app.preview is enabled (docs/rse.md).
RSE = Game("rse", tr('catalog.rse_name', 'Ruby, Sapphire & Emerald'), tr('catalog.rse_short', 'RSE'), "rse.md",
           tuple(rse_tool(tool) for tool in FRLG.tools))

LGPE_STEPS = tr('catalog.x_communicate_local_communication_trade_enter_the_same__d54e70', 'X, Communicate, Local Communication, Trade, enter the same link code, then search.')

LGPE = Game("lgpe", tr('catalog.let_s_go_pikachu_eevee_188f2e', "Let's Go Pikachu & Eevee"), tr('catalog.lgpe_26db3d', 'LGPE'), "lgpe.md", (
    Tool("lgpe-host", tr('catalog.trade_host_7198bc', 'Trade (Host)'), "bin/lgpe_host.py",
         tr('catalog.host_a_trade_under_a_link_code_the_console_joins_bf0e81', 'Host a trade under a link code; the console joins.'),
         (tr('catalog.start_the_host_first_40ac31', 'Start the host first.'), LGPE_STEPS, tr('catalog.choose_a_pokemon_and_confirm_8215d8', 'Choose a Pokemon and confirm.')),
         (queued("--offer", more="--next-offer"),
          Field("--code", tr('catalog.link_code_0b8f86', 'Link code'), "linkcode", required=True,
                help=tr('catalog.the_three_pokemon_the_player_picks_on_the_console_in_th_174ead', 'The three Pokemon the player picks on the console, in the same order.')),
          FRESH_PID,
          host_seconds("1200", tr('catalog.a_trade_under_way_when_it_runs_out_is_finished_first_5f61a0', 'A trade under way when it runs out is finished first.'))),
         fixed=("--first", "echo", "--trainer-name", "{ot}", "--our-trainer", "{tid}:{sid}",
                "--received", "{received}/lgpe-{stamp}.pb7"), doc="lgpe.md"),
    Tool("lgpe-join", tr('catalog.trade_join_8cec7d', 'Trade (Join)'), "bin/lgpe_join.py",
         tr('catalog.join_the_console_s_trade_search_2e2f10', "Join the console's trade search."),
         (tr('catalog.start_the_joiner_it_scans_for_up_to_five_minutes_9d2ad3', 'Start the joiner: it scans for up to five minutes.'), LGPE_STEPS,
          tr('catalog.offer_and_confirm_once_pokeldn_shows_queued_pokemon_fol_dec462', 'Offer and confirm once POKELDN shows. Queued Pokemon follow, one per trade.')),
         (queued("--offer"), FRESH_PID),
         fixed=("--channels", "1,6,11", "--dwell", "2.5", "--connect", "--connect-seconds", "1800",
                "--ack-peer-clock", "--ack-re-announce", "--facts", "lgpe_net_facts.json",
                "--trainer-name", "{ot}", "--our-trainer", "{tid}:{sid}",
                "--received", "{received}/lgpe-{stamp}.pb7"),
         doc="lgpe_session.md"),
))

SWSH = Game("swsh", tr('catalog.sword_shield_71b23d', 'Sword & Shield'), tr('catalog.swsh_dc0b3b', 'SwSh'), "swsh.md", (
    Tool("swsh-host", tr('catalog.trade_host_7198bc', 'Trade (Host)'), "bin/swsh_host.py", tr('catalog.host_a_link_trade_the_console_joins_9250f7', 'Host a Link Trade the console joins.'),
         (tr('catalog.start_the_host_and_wait_for_the_network_to_come_up_6d8341', 'Start the host and wait for the network to come up.'),
          tr('catalog.y_comm_link_trade_local_communication_press_a_on_both_m_19fa15', 'Y-Comm, Link Trade, local communication; press A on both messages, then wait in the overworld.'),
          tr('catalog.choose_a_pokemon_and_confirm_when_pokeldn_appears_c5c28c', 'Choose a Pokemon and confirm when POKELDN appears.'),
          tr('catalog.queued_pokemon_follow_one_per_trade_pick_again_from_the_06fa29', 'Queued Pokemon follow, one per trade: pick again from the box.')),
         (queued("--offer-file"), FRESH_PID,
          Field("--code", tr('catalog.link_code_cc04a1', 'Link Code'), "code", help=tr('catalog.eight_digits_empty_for_a_plain_trade_adde63', 'Eight digits. Empty for a plain trade.')),
          Field("--channel", tr('catalog.channel_ce4683', 'Channel'), "choice", default="6", choices=CHANNELS, help=CHANNEL_HELP, hidden=True),
          host_seconds("900")),
         fixed=("--player-name", "{ot}", "--trainer-name", "{ot}",
                "--trainer-tid", "{tid}", "--trainer-sid", "{sid}",
                "--received", "{received}/swsh-{stamp}.pk8"), doc="swsh_trade.md"),
    Tool("swsh-join", tr('catalog.trade_join_8cec7d', 'Trade (Join)'), "bin/swsh_connect.py", tr('catalog.join_the_console_s_link_trade_search_52ee13', "Join the console's Link Trade search."),
         (tr('catalog.y_comm_link_trade_local_communication_no_code_press_a_o_db5138', 'Y-Comm, Link Trade, local communication, no code; press A on both messages.'),
          tr('catalog.start_the_joiner_while_the_console_searches_5f19a9', 'Start the joiner while the console searches.'),
          tr('catalog.pokeldn_appears_on_the_trade_screen_choose_a_pokemon_an_18ef79', 'POKELDN appears on the trade screen: choose a Pokemon and confirm.'),
          tr('catalog.queued_pokemon_follow_one_per_trade_pick_again_from_the_06fa29', 'Queued Pokemon follow, one per trade: pick again from the box.')),
         (queued("--offer-file", required=False,
                 help=tr('catalog.pick_a_species_pkhex_builds_a_legal_one_empty_offers_yo_899d7f', 'Pick a species; PKHeX builds a legal one. Empty offers your own first party Pokemon back, renamed POKELDN.')),
          FRESH_PID,
          join_seconds("900")),
         fixed=("--preset", "trade", "--send-snapshot", "live",
                "--snapshot-name", "{ot}", "--snapshot-tid", "{tid}", "--snapshot-sid", "{sid}",
                "--save-offered", "{received}/swsh-{stamp}.pk8"),
         doc="swsh_trade.md"),
    Tool("swsh-gift", tr('catalog.mystery_gift_68b50f', 'Mystery Gift'), "bin/swsh_gift_host.py",
         tr('catalog.send_a_local_wireless_gift_choose_a_preset_an_official__e32c41', 'Send a local wireless gift: choose a preset, an official event, or build your own.'),
         (tr('catalog.mystery_gift_receive_a_gift_via_local_wireless_0c1758', 'Mystery Gift, Receive a Gift, via local wireless.'),
          tr('catalog.start_the_host_the_card_is_listed_within_a_few_seconds__8fbdcc', 'Start the host: the card is listed within a few seconds or not at all.'),
          tr('catalog.accept_the_card_then_stop_the_host_e08246', 'Accept the card, then stop the host.')),
         (Field("--gift-file", tr('catalog.gift_1a596a', 'Gift'), "builder"),
          Field("--seconds", tr('catalog.time_limit_seconds_cf9965', 'Time limit (seconds)'), "number", default="300", hidden=True,
                help=tr('catalog.how_long_the_card_is_advertised_after_start_0dba41', 'How long the card is advertised after Start.'))),
         doc="swsh_gift.md"),
    Tool("swsh-raid-host", tr('catalog.max_raid_host_5d0e1a', 'Max Raid (Host)'), "bin/swsh_host.py",
         tr('catalog.host_a_max_raid_the_console_joins_you_choose_the_boss_i_7c2f41', 'Host a Max Raid the console joins: you choose the boss, its rewards and the Pokemon we bring.'),
         (tr('catalog.choose_the_boss_the_pokemon_our_player_brings_and_if_yo_3b8e90', 'Choose the boss, the Pokemon our player brings and, if you like, the rewards.'),
          tr('catalog.start_the_host_9b26a9', 'Start the host.'),
          tr('catalog.y_comm_in_local_wireless_mode_join_pokeldn_s_raid_from__a91d47', "Y-Comm in local wireless mode: join POKELDN's raid from the list."),
          tr('catalog.press_ready_the_console_runs_the_battle_and_our_pokemon_6f02b3', 'Press Ready: the console runs the battle and our Pokemon fights at your side.'),
          tr('catalog.win_the_raid_to_receive_the_rewards_dcd72e', 'Win the raid to receive the rewards.')),
         (Field("--raid-event", tr('catalog.raid_event_d4b4e5', 'Raid event'), "raidevent",
                help=tr('catalog.a_boss_from_a_past_wild_area_event_from_project_pokemon_3e1f70', "A boss from a past Wild Area Event, from Project Pokemon's EventsGallery. Leave it empty, or fold this card, to host the boss you build.")),
          Field(("--raid-version", "--raid-stars", "--raid-event-boss", "--raid-area"), tr('catalog.event_boss_6b2a9d', 'Event boss'),
                "raideventboss", requires="--raid-event",
                help=tr('catalog.the_event_s_bosses_a_den_can_show_with_their_stars_leve_0c58e2', "The event's bosses a den can show, with their stars, level and game; the event's rewards that fit the den go with it.")),
          Field("--raid-boss", tr('catalog.boss_8f6c1d', 'Boss'), "pokemon", required=True, unless="--raid-event",
                help=tr('catalog.the_raid_s_boss_a_boss_a_den_can_hold_shows_in_every_co_e2a7b9', "The raid's boss. A boss a den can hold shows in every console's list; its level sets the stars.")),
          Field("--raid-gigantamax", tr('catalog.gigantamax_boss_0a7e52', 'Gigantamax boss'), "switch", unless="--raid-event",
                help=tr('catalog.for_a_pokemon_a_den_holds_as_gigantamax_charizard_snorl_6b1d40', 'For a Pokemon a den holds as Gigantamax: Charizard, Snorlax, Toxtricity and the other Gigantamax Pokemon.')),
          Field("--offer-file", tr('catalog.our_pokemon_14a66b', 'Our Pokemon'), "pokemon", required=True,
                help=tr('catalog.the_pokemon_our_player_brings_pkhex_checks_it_is_legal_abc1cf', 'The Pokemon our player brings. PKHeX checks it is legal.')),
          Field("--raid-reward", tr('catalog.rewards_59afe4', 'Rewards'), "rewards",
                help=tr('catalog.leave_empty_for_the_den_s_own_rewards_or_choose_up_to_va_91e2d4', "Leave empty for the den's own rewards, or choose up to {value0} of the rewards the boss's den gives.", value0=SWSH_REWARD_ROWS)),
          Field("--channel", tr('catalog.channel_ce4683', 'Channel'), "choice", default="6", choices=CHANNELS, help=CHANNEL_HELP, hidden=True),
          host_seconds("900")),
         fixed=("--raid-console-serves", "--player-name", "{ot}", "--trainer-name", "{ot}",
                "--trainer-tid", "{tid}", "--trainer-sid", "{sid}"), doc="swsh_raid.md"),
    Tool("swsh-lair-raid-host", tr('catalog.dynamax_adventure_host_4c81e2', 'Dynamax Adventure (Host)'), "bin/swsh_host.py",
         tr('catalog.host_a_dynamax_adventure_the_console_joins_you_choose_t_9a3f17', 'Host a Dynamax Adventure the console joins: you choose the legendary at the end of the Max Lair.'),
         (tr('catalog.choose_the_legendary_then_start_the_host_5be0c4', 'Choose the legendary, then start the host.'),
          tr('catalog.at_the_max_lair_talk_to_the_receptionist_press_to_set_t_8d4b19', 'At the Max Lair, talk to the receptionist, press + to set the same Link Code if you chose one, then choose Invite Others.'),
          tr('catalog.press_ready_once_pokeldn_is_in_the_lobby_80d6b3', 'Press Ready once POKELDN is in the lobby.'),
          tr('catalog.pokeldn_leaves_once_the_adventure_starts_a_computer_par_2c7f05', 'POKELDN leaves once the adventure starts: a computer partner takes its seat and the adventure goes on.')),
         (Field("--lair-legendary", tr('catalog.legendary_6e94a1', 'Legendary'), "choice", default="150",
                choices=SWSH_LAIR_LEGENDARIES,
                help=tr('catalog.the_legendary_pokemon_waiting_at_the_end_of_the_max_lai_b0d3e8', 'The legendary Pokemon waiting at the end of the Max Lair.')),
          Field("--code", tr('catalog.link_code_cc04a1', 'Link Code'), "code",
                help=tr('catalog.eight_digits_the_console_sets_with_at_the_receptionist__5a8e30', 'Eight digits, set on the console with + at the receptionist. Empty for none.')),
          Field("--lair-seed", tr('catalog.adventure_seed_1f7c55', 'Adventure seed'), "lairseed", template="0x{}",
                help=tr('catalog.sets_the_rental_pokemon_and_the_pokemon_met_on_the_way_e4b8d2', 'Sets the rental Pokemon and the Pokemon met on the way. Leave empty for a random one.')),
          Field("--channel", tr('catalog.channel_ce4683', 'Channel'), "choice", default="6", choices=CHANNELS, help=CHANNEL_HELP, hidden=True),
          host_seconds("600")),
         fixed=("--player-name", "{ot}", "--trainer-name", "{ot}",
                "--trainer-tid", "{tid}", "--trainer-sid", "{sid}"), doc="swsh_raid.md"),
))

BDSP_ROOM = tr('catalog.pokemon_center_2f_left_attendant_plain_yes_no_password__35cfcc', 'Pokemon Center 2F, left attendant, plain Yes (no password, not the group option).')

BDSP = Game("bdsp", tr('catalog.brilliant_diamond_shining_pearl_f30922', 'Brilliant Diamond & Shining Pearl'), tr('catalog.bdsp_1358ba', 'BDSP'), "bdsp.md", (
    Tool("bdsp-host", tr('catalog.trade_host_7198bc', 'Trade (Host)'), "bin/bdsp_host.py",
         tr('catalog.host_a_union_room_the_console_enters_d169f8', 'Host a Union Room the console enters.'),
         (tr('catalog.start_the_host_before_the_player_enters_the_room_c8c655', 'Start the host before the player enters the room.'),
          tr('catalog.our_character_appears_4daa86', '{value0} Our character appears.', value0=BDSP_ROOM),
          tr('catalog.y_communicate_trade_pokemon_accept_the_greeting_then_ch_068c66', 'Y, Communicate, Trade Pokemon; accept the greeting, then choose and confirm.')),
         (queued("--offer"),
          FRESH_PID,
          Field("--password", tr('catalog.room_password_158a0a', 'Room password'), "code", help=tr('catalog.eight_digits_empty_for_the_plain_room_235b0d', 'Eight digits. Empty for the plain room.')),
          host_seconds("1500")),
         fixed=("--ldn-protocol", "1", "--complete-trade", "--save-theirs", "{received}/bdsp-{stamp}",
                "--language", "{language}", "--name", "{ot}", "--trainer", "{ot}:{tid}:{sid}"),
         doc="bdsp_trade.md"),
    Tool("bdsp-join", tr('catalog.trade_join_8cec7d', 'Trade (Join)'), "bin/bdsp_connect.py",
         tr('catalog.join_the_console_s_union_room_as_a_character_and_trade_e07848', "Join the console's Union Room as a character and trade."),
         (tr('catalog.wait_in_the_room_clear_of_the_walls_c546ae', '{value0} Wait in the room, clear of the walls.', value0=BDSP_ROOM),
          tr('catalog.start_the_joiner_and_wait_for_the_character_to_appear_afaf82', 'Start the joiner and wait for the character to appear.'),
          tr('catalog.y_communicate_trade_pokemon_and_wait_the_greeting_comes_ae79bc', 'Y, Communicate, Trade Pokemon, and wait: the greeting comes up on its own.'),
          tr('catalog.between_runs_leave_and_re_enter_the_room_b1e71c', 'Between runs, leave and re-enter the room.')),
         (queued("--trade-template"),
          Field("--trade-nickname", tr('catalog.nickname_d720f6', 'Nickname'), hidden=True,
                help=tr('catalog.a_nickname_given_to_every_offered_pokemon_empty_keeps_t_c4aaf8', 'A nickname given to every offered Pokemon; empty keeps the one it was built with.')),
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

PLA_STEPS = (tr('catalog.talk_to_the_trade_npc_in_jubilife_village_trade_local_p_63341c', 'Talk to the trade NPC in Jubilife Village: trade, local, past the warning.'),
             tr('catalog.enter_the_same_eight_digit_code_and_press_to_search_2d0ec5', 'Enter the same eight-digit code and press + to search.'))
PLA_OFFER_HELP = tr('catalog.pick_a_species_pkhex_builds_a_legal_one_empty_offers_po_304364', "Pick a species; PKHeX builds a legal one. Empty offers pokeldn's own Azelf.")

PLA = Game("pla", tr('catalog.legends_arceus_260415', 'Legends Arceus'), tr('catalog.pla_eafc6b', 'PLA'), "pla.md", (
    Tool("pla-host", tr('catalog.trade_host_7198bc', 'Trade (Host)'), "bin/pla_host.py",
         tr('catalog.host_a_trade_under_a_link_code_the_console_joins_bf0e81', 'Host a trade under a link code; the console joins.'),
         (tr('catalog.start_the_host_first_40ac31', 'Start the host first.'), *PLA_STEPS, tr('catalog.offer_a_pokemon_and_confirm_ae970b', 'Offer a Pokemon and confirm.'),
          tr('catalog.leave_the_host_running_until_the_trade_ends_an_interrup_adc091', 'Leave the host running until the trade ends: an interrupted trade locks trading for a while.')),
         (queued("--trade-box-record", required=False, help=PLA_OFFER_HELP),
          Field("--code", tr('catalog.link_code_0b8f86', 'Link code'), "code", default="00000000", help=CODE_HELP),
          FRESH_PID,
          host_seconds("900")),
         fixed=("--channel", "6", "--session-update", "--sustain", "--clock", "--data-exchange",
                "--game-channel", "--trade-box", "--player-name", "{ot}", "--gender", "{gender}",
                "--offer-out", "{received}/pla-{stamp}.pa8"),
         doc="pla.md"),
    Tool("pla-join", tr('catalog.trade_join_8cec7d', 'Trade (Join)'), "bin/pla_join.py",
         tr('catalog.find_your_console_s_trade_search_and_connect_automatica_388352', "Find your console's trade search and connect automatically."),
         (*PLA_STEPS, tr('catalog.start_the_joiner_84b994', 'Start the joiner.'), tr('catalog.offer_and_confirm_once_the_partner_shows_b0b40e', 'Offer and confirm once the partner shows.')),
         (queued("--offer", required=False, help=PLA_OFFER_HELP),
          Field("--code", tr('catalog.link_code_0b8f86', 'Link code'), "code", default="00000000", help=CODE_HELP),
          FRESH_PID),
         fixed=("--player-name", "{ot}", "--gender", "{gender}",
                "--offer-out", "{received}/pla-{stamp}.pa8"),
         doc="pla.md"),
))

SV_SEARCH = tr('catalog.x_poke_portal_link_trade_offline_then_search_634a34', 'X, Poke Portal, Link Trade, offline, then search.')

SV = Game("sv", tr('catalog.scarlet_violet_504657', 'Scarlet & Violet'), tr('catalog.sv_a4cd8b', 'SV'), "sv.md", (
    Tool("sv-host", tr('catalog.trade_host_7198bc', 'Trade (Host)'), "bin/sv_host.py",
         tr('catalog.host_a_trade_the_searching_console_joins_d5a11b', 'Host a trade the searching console joins.'),
         (tr('catalog.start_the_host_first_40ac31', 'Start the host first.'), SV_SEARCH, tr('catalog.offer_and_confirm_on_the_trade_screen_7d393b', 'Offer and confirm on the trade screen.')),
         (queued("--trade-offer"),
          Field("--code", tr('catalog.link_code_cc04a1', 'Link Code'), "code", help=tr('catalog.empty_hosts_a_search_with_no_code_6d9fdd', 'Empty hosts a search with no code.'),
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
    Tool("sv-join", tr('catalog.trade_join_8cec7d', 'Trade (Join)'), "bin/sv_join.py",
         tr('catalog.join_the_console_s_link_trade_search_52ee13', "Join the console's Link Trade search."),
         (SV_SEARCH, tr('catalog.start_the_joiner_84b994', 'Start the joiner.'), tr('catalog.offer_and_confirm_on_the_trade_screen_7d393b', 'Offer and confirm on the trade screen.'),
          tr('catalog.if_the_console_keeps_refusing_leave_and_re_enter_the_se_28b562', 'If the console keeps refusing, leave and re-enter the search screen.')),
         (queued("--trade-offer"),
          Field("--code", tr('catalog.link_code_cc04a1', 'Link Code'), "code", help=tr('catalog.empty_joins_a_search_with_no_code_caae9d', 'Empty joins a search with no code.')),
          FRESH_PID),
         fixed=("--phy", "auto", "--seconds", "1500", "--hold", "900", "--channels", "1,6,11",
                "--dwell", "0.4", "--connect-timeout", "6", "--open-delay", "0.3", "--record-delay", "0.3",
                "--session-join", "--answer-migration", "--net-ack", "--ack-flags", "0x00",
                "--game-channel", "--announce-timeout", "20", "--rtt-delay", "0.3",
                "--trainer-name", "{ot}", "--offer-out", "{received}/sv-{stamp}.pk9"), doc="sv.md"),
    Tool("sv-raid-host", tr('catalog.tera_raid_host_d3c097', 'Tera Raid (Host)'), "bin/sv_host.py",
         tr('catalog.host_a_tera_raid_the_console_joins_you_choose_the_raid__ba0395', 'Host a Tera Raid the console joins: you choose the raid, its rewards and the Pokemon we bring.'),
         (tr('catalog.choose_the_pokemon_our_player_brings_the_raid_and_if_yo_c1ebd8', 'Choose the Pokemon our player brings, the raid and, if you like, its rewards.'),
          tr('catalog.start_the_host_9b26a9', 'Start the host.'),
          tr('catalog.on_each_console_x_poke_portal_tera_raid_battle_search_o_3b317a', 'On each console: X, Poke Portal, Tera Raid Battle, search offline, Link Code 4970.'),
          tr('catalog.press_ready_on_each_console_the_raid_starts_once_every__8c975c', 'Press Ready on each console: the raid starts once every console is in and Ready, or when the lobby timer runs out.'),
          tr('catalog.our_player_leaves_when_the_battle_starts_its_pokemon_st_284730', 'Our player leaves when the battle starts; its Pokemon stays and fights at your side.'),
          tr('catalog.a_communication_error_may_show_as_the_battle_starts_dis_fd7b88', 'A communication error may show as the battle starts: dismiss it and fight on.'),
          tr('catalog.win_the_raid_to_receive_the_rewards_dcd72e', 'Win the raid to receive the rewards.')),
         (Field("--raid-pokemon", tr('catalog.our_pokemon_14a66b', 'Our Pokemon'), "pokemon", required=True,
                help=tr('catalog.the_pokemon_our_player_brings_pkhex_checks_it_is_legal_abc1cf', 'The Pokemon our player brings. PKHeX checks it is legal.')),
          Field("--raid-event", tr('catalog.raid_event_d4b4e5', 'Raid event'), "raidevent",
                help=tr('catalog.a_raid_from_a_past_poke_portal_news_event_from_project__17be6a', "A raid from a past Poke Portal News event, from Project Pokemon's EventsGallery. Leave it empty, or fold this card, for a standard raid.")),
          Field("--raid-version", tr('catalog.game_5c412a', 'Game'), "choice", default="violet", group=tr('catalog.the_raid_a6f6bf', 'The raid'),
                choices=(("scarlet", tr('catalog.scarlet_f11da0', 'Scarlet')), ("violet", tr('catalog.violet_2a3642', 'Violet'))),
                help=tr('catalog.a_seed_can_give_another_raid_in_the_other_version_bf545f', 'A seed can give another raid in the other version.')),
          Field("--raid-map", tr('catalog.region_d3a008', 'Region'), "choice", default="paldea", group=tr('catalog.the_raid_a6f6bf', 'The raid'),
                choices=(("paldea", tr('catalog.paldea_14c1fa', 'Paldea')), ("kitakami", tr('catalog.kitakami_44ab29', 'Kitakami')), ("blueberry", tr('catalog.blueberry_d20244', 'Blueberry')))),
          Field("--raid-progress", tr('catalog.story_progress_d527c5', 'Story progress'), "choice", default="4star", group=tr('catalog.the_raid_a6f6bf', 'The raid'),
                choices=(("beginning", tr('catalog.beginning_9e6b41', 'Beginning')), ("tera", tr('catalog.tera_raids_unlocked_07d442', 'Tera Raids unlocked')),
                         ("3star", tr('catalog.3_star_raids_e72615', '3-star raids')), ("4star", tr('catalog.4_star_raids_d82c77', '4-star raids')),
                         ("5star", tr('catalog.5_star_raids_d693f5', '5-star raids')), ("6star", tr('catalog.6_star_raids_e7e30a', '6-star raids'))),
                help=tr('catalog.sets_how_many_stars_a_standard_crystal_can_have_fb17ea', 'Sets how many stars a standard crystal can have.')),
          Field("--raid-content", tr('catalog.crystal_b8c18c', 'Crystal'), "choice", default="standard", group=tr('catalog.the_raid_a6f6bf', 'The raid'),
                choices=(("standard", tr('catalog.standard_ef6691', 'Standard')), ("black", tr('catalog.black_6_stars_3ee5de', 'Black (6 stars)'))), unless="--raid-event"),
          Field("--raid-event-group", tr('catalog.crystal_b8c18c', 'Crystal'), "raidden", group=tr('catalog.the_raid_a6f6bf', 'The raid'), requires="--raid-event",
                help=tr('catalog.each_of_the_event_s_crystals_has_its_own_bosses_628ee4', "Each of the event's crystals has its own bosses.")),
          Field("--raid-seed", tr('catalog.raid_seed_e70045', 'Raid seed'), "raidseed", default="000F34C3", required=True,
                group=tr('catalog.the_raid_a6f6bf', 'The raid'), help=tr('catalog.eight_hexadecimal_digits_find_a_raid_searches_seeds_for_b8aa2b', 'Eight hexadecimal digits. Find a raid searches seeds for you.')),
          Field("--raid-reward", tr('catalog.rewards_59afe4', 'Rewards'), "rewards",
                help=tr('catalog.leave_empty_for_the_raid_s_own_rewards_or_list_up_to_it_6e5d73', "Leave empty for the raid's own rewards, or list up to {value0} items.", value0=REWARD_ROWS)),
          Field("--raid-players", tr('catalog.consoles_joining_7a43ed', 'Consoles joining'), "choice", default="1",
                choices=(("1", tr('catalog.1_console_90b18a', '1 console')), ("2", tr('catalog.2_consoles_5e36d3', '2 consoles')), ("3", tr('catalog.3_consoles_af51df', '3 consoles'))),
                help=tr('catalog.the_raid_waits_for_this_many_consoles_each_one_ready_be_60226a', 'The raid waits for this many consoles, each one Ready, before it starts. Each console then fights its own copy of the battle.')),
          Field(("--raid-partner", "--raid-partner-progress"), tr('catalog.raid_npc_partners_c62ef4', 'Raid NPC partners'), "raidpartners",
                help=tr('catalog.the_trainers_who_fill_the_slots_no_console_holds_two_wi_906d17', 'The trainers who fill the slots no console holds: two with one console joining, one with two, none with three. A slot you leave unpicked gets a trainer the game draws.')),
          Field("--raid-catch-normal", tr('catalog.catch_an_event_boss_again_f24ceb', 'Catch an event boss again'), "switch", hidden=True,
                requires="--raid-event",
                help=tr('catalog.offer_a_boss_the_event_lets_a_save_catch_once_as_a_norm_0ebdc3', 'Offer a boss the event lets a save catch once as a normal catch, under a record number no save has caught. The Raid event card sets it.')),
          host_seconds("600")),
         fixed=("--channel", "1", "--scene-id", "7", "--max-participants", "4", "--code", "4970",
                "--scarlet-response", "--session-flags", "0", "--session-packet-id", "1",
                "--no-session-ack", "--join-seq", "0", "--update-seq", "0", "--update-delay", "0.02",
                "--rtt-probe", "--clock", "--net-stations", "4", "--record-delay", "0.1",
                "--record-spacing", "0.003", "--host-player-id", "00000000000000010000000000000000",
                "--host-player-name", "{ot}", "--trainer-name", "{ot}"),
         doc="sv_raid.md"),
    Tool("sv-raid-join", tr('catalog.tera_raid_join_75d587', 'Tera Raid (Join)'), "bin/sv_join.py",
         tr('catalog.join_a_tera_raid_the_console_hosts_and_leave_one_of_you_b6a64d', 'Join a Tera Raid the console hosts and leave one of your Pokemon to fight in it.'),
         (tr('catalog.on_the_console_a_tera_raid_crystal_challenge_as_a_group_d752cd', 'On the console: a Tera Raid crystal, Challenge as a group, and wait for players.'),
          tr('catalog.choose_the_pokemon_our_player_brings_then_start_the_joi_571094', 'Choose the Pokemon our player brings, then start the joiner.'),
          tr('catalog.our_player_joins_and_readies_start_the_battle_on_the_co_edacf9', 'Our player joins and readies; start the battle on the console.'),
          tr('catalog.our_player_leaves_as_the_battle_starts_its_pokemon_figh_421b73', 'Our player leaves as the battle starts; its Pokemon fights on as a partner.')),
         (Field("--raid-pokemon", tr('catalog.our_pokemon_14a66b', 'Our Pokemon'), "pokemon", required=True,
                help=tr('catalog.the_pokemon_our_player_brings_pkhex_checks_it_is_legal_abc1cf', 'The Pokemon our player brings. PKHeX checks it is legal.')),
          join_seconds("240")),
         fixed=("--seconds", "900", "--name", 'POKELDN', "--trainer-name", "{ot}"),
         doc="sv_raid.md"),
    Tool("sv-circle-join", tr('catalog.union_circle_quests_6ec3ee', 'Union Circle - Quests'), "bin/sv_join.py",
         tr('catalog.join_the_union_circle_the_console_hosts_and_clear_blueb_a7f910', 'Join the Union Circle the console hosts and clear Blueberry Quests for it: every Snacksworth legendary, or the BP you choose.'),
         (tr('catalog.on_the_console_x_poke_portal_union_circle_then_start_a__28de4e', 'On the console: X, Poke Portal, Union Circle, then start a group playing locally under a Link Code.'),
          tr('catalog.enter_the_same_link_code_here_choose_the_task_and_start_0dffcf', 'Enter the same Link Code here, choose the task and start.'),
          (tr('catalog.once_pokeldn_is_in_the_group_start_the_circle_on_the_co_0d4e89', 'Once POKELDN is in the group, start the circle on the console. As its start demo ends, the quests go in one a second, then our player leaves.'),
           ("--circle-task", "snacksworth")),
          (tr('catalog.once_pokeldn_is_in_the_group_start_the_circle_on_the_co_7a9a17', 'Once POKELDN is in the group, start the circle on the console. As its start demo ends, the BP clear goes in, then our player leaves.'),
           ("--circle-task", "bp")),
          tr('catalog.close_the_bp_side_bar_on_the_console_to_see_the_bp_come_bd0b25', 'Close the BP side bar on the console to see the BP come in.'),
          (tr('catalog.for_snacksworth_talk_to_him_once_for_each_legendary_eac_87f6c8', 'For Snacksworth, talk to him once for each legendary; each talk releases one.'),
           ("--circle-task", "snacksworth"))),
         (Field("--code", tr('catalog.link_code_cc04a1', 'Link Code'), "code", required=True, length=4,
                remembered=False,
                help=tr('catalog.the_union_circle_s_four_digit_link_code_2e76dc', "The Union Circle's four-digit Link Code.")),
          Field("--circle-task", tr('catalog.task_4bc74b', 'Task'), "choice", default="snacksworth",
                choices=(("snacksworth", tr('catalog.unlock_all_remaining_snacksworth_legendaries_cd6e98', 'Unlock all remaining Snacksworth legendaries')),
                         ("bp", tr('catalog.give_bp_b0e117', 'Give BP'))),
                choice_help=(("snacksworth", tr('catalog.reads_how_many_solo_and_team_quests_the_host_still_lack_55eb31', "Reads how many solo and Team quests the host still lacks of the 130 and 12 that release all 25 legendaries, then gives them, one a second: Team quests drawn as the game draws them, then the host's own solo quests as they come up.")),
                             ("bp", tr('catalog.clears_one_quest_for_the_host_that_pays_this_bp_2c54b4', 'Clears one quest for the host that pays this BP.')))),
          Field("--bbq-clear", tr('catalog.bp_36b717', 'BP'), "number", default="1000", required=True,
                when=("--circle-task", "bp"), bounds=(1, BP_MAX),
                help=tr('catalog.from_1_to_9_999_999_the_most_bp_a_player_holds_99d199', 'From 1 to 9,999,999, the most BP a player holds.')),
          join_seconds("900")),
         fixed=("--union-circle", "--seconds", "900", "--name", 'POKELDN', "--trainer-name", "{ot}"),
         doc="sv_union_circle.md"),
    Tool("sv-circle-encounters-join", tr('catalog.union_circle_encounters_31663b', 'Union Circle - Encounters'), "bin/sv_join.py",
         tr('catalog.join_the_union_circle_the_console_hosts_and_spawn_the_w_88db74', 'Join the Union Circle the console hosts and spawn the wild Pokemon you craft around its player, to battle and catch.'),
         (tr('catalog.on_the_console_x_poke_portal_union_circle_then_start_a__28de4e', 'On the console: X, Poke Portal, Union Circle, then start a group playing locally under a Link Code.'),
          tr('catalog.enter_the_same_link_code_here_craft_the_pokemon_and_sta_23247e', 'Enter the same Link Code here, craft the Pokemon and start.'),
          tr('catalog.once_pokeldn_is_in_the_group_start_the_circle_on_the_co_c34ac9', 'Once POKELDN is in the group, start the circle on the console. As its start demo ends, our player follows yours.'),
          tr('catalog.three_of_the_pokemon_come_15_to_25_m_around_you_one_you_47e6f7', 'Three of the Pokemon come 15 to 25 m around you. One you battle, or walk more than 50 m from, comes back near you.'),
          tr('catalog.with_legal_encounters_only_they_wait_until_the_wild_pok_aca8b5', 'With Legal encounters only they wait until the wild Pokemon your game shares show you stand where PKHeX accepts them caught, and go when you walk 50 m from where that was found.'),
          tr('catalog.close_the_circle_on_the_console_to_stop_fa751d', 'Close the circle on the console to stop.')),
         (Field("--code", tr('catalog.link_code_cc04a1', 'Link Code'), "code", required=True, length=4,
                remembered=False,
                help=tr('catalog.the_union_circle_s_four_digit_link_code_2e76dc', "The Union Circle's four-digit Link Code.")),
          Field("--spawn", tr('catalog.pokemon_to_spawn_c7ecd1', 'Pokemon to spawn'), "encounter", required=True,
                help=tr('catalog.the_wild_pokemon_that_appears_around_you_in_the_game_to_c2e57e', 'The wild Pokemon that appears around you in the game, to battle and catch.')),
          join_seconds("3600")),
         fixed=("--union-circle", "--seconds", "3600", "--follow-host", "--name", 'POKELDN',
                "--trainer-name", "{ot}"),
         doc="sv_union_circle.md"),
))

ZA = Game("za", tr('catalog.legends_z_a_594c26', 'Legends Z-A'), tr('catalog.plza_bc9316', 'PLZA'), "za.md", (
    Tool("za-host", tr('catalog.trade_host_7198bc', 'Trade (Host)'), "bin/za_host.py",
         tr('catalog.host_a_trade_the_searching_console_joins_d5a11b', 'Host a trade the searching console joins.'),
         (tr('catalog.start_the_host_first_40ac31', 'Start the host first.'),
          tr('catalog.x_link_play_link_trade_nearby_players_the_same_code_the_b0f613', 'X, Link Play, Link Trade, Nearby Players, the same code, then search.'),
          tr('catalog.pick_on_the_trade_box_offer_then_trade_queued_pokemon_f_5554fc', 'Pick on the trade box, offer, then trade. Queued Pokemon follow, one per trade.'),
          tr('catalog.back_out_with_b_after_the_last_trade_97a1dc', 'Back out with B after the last trade.')),
         (queued("--trade-offer"),
          Field("--code", tr('catalog.link_code_0b8f86', 'Link code'), "code", default="00000000", help=CODE_HELP),
          FRESH_PID,
          host_seconds("900")),
         fixed=("--trainer-name", "{ot}", "--offer-out", "{received}/za-{stamp}.pa9"), doc="za.md"),
    Tool("za-join", tr('catalog.trade_join_8cec7d', 'Trade (Join)'), "bin/za_join.py",
         tr('catalog.join_the_console_s_link_trade_search_52ee13', "Join the console's Link Trade search."),
         (tr('catalog.link_trade_local_communication_search_with_the_link_cod_4e7c15', 'Link Trade, local communication, search with the link code.'),
          tr('catalog.start_the_joiner_refusals_while_seating_are_normal_let__2e1cb1', 'Start the joiner. Refusals while seating are normal; let it run.'),
          tr('catalog.pick_on_the_trade_box_and_confirm_once_pokeldn_appears__693ece', 'Pick on the trade box and confirm once POKELDN appears. Queued Pokemon follow, one per trade.')),
         (queued("--trade-offer"),
          Field("--code", tr('catalog.link_code_0b8f86', 'Link code'), "code", default="00000000", help=CODE_HELP),
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
        return (replace(f, identity="#Mystery Gift Pokemon" if not f.flag else f.identity, label=tr('catalog.mystery_gift_pokemon_e3340b', 'Mystery Gift Pokemon'), required=True, events=True, queue=QUEUE,
                        help=tr('catalog.every_pokemon_gift_gave_from_pkhex_s_event_database_add_cbef41', "Every Pokemon gift {value0} gave, from PKHeX's event database. Add up to {value1}; one session trades them in order, each as a fresh legal copy.", value0=game.name, value1=QUEUE)),
                FOR_RECEIVER)
    return Tool(host.key.replace("-host", "-gift-host"), tr('catalog.mystery_gift_simulated_d9d548', 'Mystery Gift - Simulated'), host.script,
                tr('catalog.trade_an_official_mystery_gift_pokemon_to_the_console_a_a079f5', 'Trade an official Mystery Gift Pokemon to the console: a fresh legal copy, as your trainer received it.'), steps, tuple(g for f in host.fields for g in gift(f)), fixed=host.fixed,
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
                       tr('catalog.the_three_pokemon_you_and_your_partner_pick_in_the_same_a31f1a', 'The three Pokemon you and your partner pick, in the same order, here and on the console.'))
    at = max(n for n, t in enumerate(game.tools) if t.key in trade_keys(game)) + 1   # after Join
    return replace(game, tools=game.tools[:at] + (online(host, steps, code),) + game.tools[at:])


GAMES = (
    with_online(FRLG, (tr('catalog.join_group_then_pick_pokeldn_125fa7', '{value0}, Join Group, then pick POKELDN.', value0=FRLG_PATH),
                       tr('catalog.your_partner_s_party_shows_on_the_right_choose_the_poke_ca7e7b', "Your partner's party shows on the right: choose the Pokemon you send, then confirm.")),
                Field("--online-code", tr('catalog.code_340f46', 'Code'), "code", help=ONLINE_CODE_HELP)),
    with_online(with_gift(LGPE, (tr('catalog.choose_the_event_pokemon_then_start_the_host_51919d', 'Choose the event Pokemon, then start the host.'), LGPE_STEPS, GIFT_OFFER_BACK)),
                (LGPE_STEPS, tr('catalog.choose_a_pokemon_and_confirm_8215d8', 'Choose a Pokemon and confirm.'))),
    with_online(SWSH, (tr('catalog.y_comm_link_trade_local_communication_with_the_same_lin_316b85', 'Y-Comm, Link Trade, local communication with the same Link Code; press A on both messages, then wait in the overworld.'),
                       tr('catalog.choose_the_pokemon_to_send_when_pokeldn_appears_bb19f5', 'Choose the Pokemon to send when POKELDN appears.'))),
    with_online(with_gift(BDSP, (tr('catalog.choose_the_event_pokemon_then_start_the_host_before_the_2416a8', 'Choose the event Pokemon, then start the host before the player enters the room.'), tr('catalog.our_character_appears_4daa86', '{value0} Our character appears.', value0=BDSP_ROOM),
                                 tr('catalog.y_communicate_trade_pokemon_accept_the_greeting_bc6aa6', 'Y, Communicate, Trade Pokemon; accept the greeting.'), GIFT_OFFER_BACK)),
                (tr('catalog.our_character_appears_4daa86', '{value0} Our character appears.', value0=BDSP_ROOM),
                 tr('catalog.y_communicate_trade_pokemon_accept_the_greeting_then_ch_2c7215', 'Y, Communicate, Trade Pokemon; accept the greeting, then choose.')),
                Field("--password", tr('catalog.code_340f46', 'Code'), "code", help=tr('catalog.eight_digits_you_and_your_partner_agree_on_you_also_ent_a2a06f', "Eight digits you and your partner agree on; you also enter them at the Union Room's password prompt. Empty: the plain room, and anyone trading online without a code."))),
    with_online(with_gift(PLA, (tr('catalog.choose_the_event_pokemon_then_start_the_host_51919d', 'Choose the event Pokemon, then start the host.'), *PLA_STEPS, GIFT_OFFER_BACK,
                                tr('catalog.leave_the_host_running_until_the_trade_ends_an_interrup_adc091', 'Leave the host running until the trade ends: an interrupted trade locks trading for a while.'))),
                (*PLA_STEPS, tr('catalog.offer_a_pokemon_and_confirm_ae970b', 'Offer a Pokemon and confirm.'))),
    with_online(with_gift(SV, (tr('catalog.choose_the_event_pokemon_then_start_the_host_51919d', 'Choose the event Pokemon, then start the host.'), SV_SEARCH, GIFT_OFFER_BACK)),
                (SV_SEARCH, tr('catalog.offer_and_confirm_on_the_trade_screen_7d393b', 'Offer and confirm on the trade screen.'))),
    with_online(with_gift(ZA, (tr('catalog.choose_the_event_pokemon_then_start_the_host_51919d', 'Choose the event Pokemon, then start the host.'),
                               tr('catalog.x_link_play_link_trade_nearby_players_the_same_code_the_b0f613', 'X, Link Play, Link Trade, Nearby Players, the same code, then search.'),
                               tr('catalog.pick_a_pokemon_you_caught_in_this_save_on_the_trade_box_855d95', 'Pick a Pokemon you caught in this save on the trade box, then trade. The event Pokemon comes over; yours goes to Received. Trade again for each queued gift.'),
                               tr('catalog.back_out_with_b_after_the_last_trade_97a1dc', 'Back out with B after the last trade.'))),
                (tr('catalog.x_link_play_link_trade_nearby_players_the_same_code_the_b0f613', 'X, Link Play, Link Trade, Nearby Players, the same code, then search.'),
                 tr('catalog.pick_on_the_trade_box_offer_then_trade_b0a22c', 'Pick on the trade box, offer, then trade.'))),
)

if preview.enabled():
    GAMES = GAMES[:1] + (with_online(RSE, (tr('catalog.join_group_then_pick_pokeldn_125fa7', '{value0}, Join Group, then pick POKELDN.', value0=FRLG_PATH),
                                           tr('catalog.your_partner_s_party_shows_on_the_right_choose_the_poke_ca7e7b', "Your partner's party shows on the right: choose the Pokemon you send, then confirm.")),
                                     Field("--online-code", tr('catalog.code_340f46', 'Code'), "code", help=ONLINE_CODE_HELP)),) + GAMES[1:]
