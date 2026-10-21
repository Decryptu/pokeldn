from pokeldn.app.i18n import ref as _ref
"""The NPC trainers a Tera Raid seats in the slots no player holds (docs/sv_raid.md, Partners): their
table, the trainers a partner seed draws from the pool the host's unlock stage picks, and a seed that
draws the trainers asked for."""

import json
import os
from dataclasses import dataclass
from functools import cache

from pokeldn.sv import raid_encounter

# The RaidPoint's u32 at 0x3e0 is the host's raid unlock stage, the game's progress less one: 0 Tera
# Raids unlocked (one and two stars) to 4 six stars, the highest difficulty flag set [0xe2826c]. 5 drew broken partners on a retail Scarlet and
# crashed its battle later.
STAGES = raid_encounter.PROGRESS[1:]
SIX_STARS = len(STAGES) - 1
# The partners a pokeldn raid seats with one console: our player and the console hold the other two
# of the four slots. Each further console takes one (`slots`).
HOSTED = 2

TRAINERS = (_ref("core.pokeldn.sv.raid_partners.austin_a161e03b"), "Ava", "Logan", _ref("core.pokeldn.sv.raid_partners.hailey_88fa3283"), "Evan", _ref("core.pokeldn.sv.raid_partners.charlotte_2e7041b7"), "Kylie", _ref("core.pokeldn.sv.raid_partners.hunter_680ce380"), _ref("core.pokeldn.sv.raid_partners.gianna_30598429"),
            "Eli", "Henry", "Chase", _ref("core.pokeldn.sv.raid_partners.claire_4660c3e4"), _ref("core.pokeldn.sv.raid_partners.brooklyn_a1ff4142"), "Zoe", _ref("core.pokeldn.sv.raid_partners.samantha_7a49d0e3"), "Dylan", "Luke")


@dataclass(frozen=True)
class Partner:
    trainer: str
    species: int        # National Dex number
    name: str
    level: int          # Serebii's: a partner's beside a Lv 20, 50 or 100 host Pokemon (`level_for`)
    ability: str
    moves: tuple
    tera: str
    rank: int = 0       # 1 the partners raiders favour, 2 the next tier, 0 the rest
    why: str = ""       # why raiders want this partner, in a few words; "" for most
    detail: str = ""    # `why` at more length
    trainer_key: str = ""
    form: int = 0
    move_ids: tuple[int, ...] = ()
    ability_id: int = 0
    tera_type_id: int = 0


# (species, name, ability, moves, Tera type) per trainer in draw order, by the pool's level, as
# Serebii's Tera Raid Battle partners page lists them; the game's tables (`game_pool`) agree but
# for Henry's Tera type, Steel where Serebii says random. Dylan's Haxorus and Luke's Clodsire take
# their species' default Tera type, Dragon and Ground as a retail console showed them.
# Dylan and Luke are not in the level-16 pool.
POOLS = {
    16: (
        (58, "Growlithe", _ref("core.pokeldn.sv.raid_partners.intimidate_7879eb29"), ("Ember", "Leer", "Bite"), "Fire"),
        (418, "Buizel", _ref("core.pokeldn.sv.raid_partners.swift_swim_3e76a1ef"), (_ref("core.pokeldn.sv.raid_partners.aqua_jet_0c3e802b"), "Bite", _ref("core.pokeldn.sv.raid_partners.water_gun_02479083")), "Water"),
        (672, "Skiddo", _ref("core.pokeldn.sv.raid_partners.sap_sipper_51734022"), (_ref("core.pokeldn.sv.raid_partners.tackle_9c0dd009"), _ref("core.pokeldn.sv.raid_partners.vine_whip_6f2345e5"), _ref("core.pokeldn.sv.raid_partners.growth_66b06e99")), "Grass"),
        (81, "Magnemite", _ref("core.pokeldn.sv.raid_partners.magnet_pull_79a510d3"), (_ref("core.pokeldn.sv.raid_partners.thunder_shock_754e401d"), _ref("core.pokeldn.sv.raid_partners.thunder_wave_96bd41f8"), "Swift"), _ref("core.pokeldn.sv.raid_partners.electric_a76dab2d")),
        (819, "Skwovet", _ref("core.pokeldn.sv.raid_partners.cheek_pouch_89d10697"), (_ref("core.pokeldn.sv.raid_partners.tackle_9c0dd009"), _ref("core.pokeldn.sv.raid_partners.defense_curl_6b72015c"), _ref("core.pokeldn.sv.raid_partners.rollout_b14395be")), _ref("core.pokeldn.sv.raid_partners.normal_a7248eeb")),
        (397, "Staravia", _ref("core.pokeldn.sv.raid_partners.intimidate_7879eb29"), (_ref("core.pokeldn.sv.raid_partners.wing_attack_a408d0ed"), _ref("core.pokeldn.sv.raid_partners.quick_attack_75427c13"), "Growl"), _ref("core.pokeldn.sv.raid_partners.flying_75a4c2fe")),
        (739, "Crabrawler", _ref("core.pokeldn.sv.raid_partners.hyper_cutter_401c1998"), (_ref("core.pokeldn.sv.raid_partners.rock_smash_5ed98022"), _ref("core.pokeldn.sv.raid_partners.bubble_beam_748a793a"), _ref("core.pokeldn.sv.raid_partners.work_up_4735e5d6")), "Grass"),
        (425, "Drifloon", _ref("core.pokeldn.sv.raid_partners.aftermath_07ac3909"), ("Gust", "Hex", _ref("core.pokeldn.sv.raid_partners.payback_debb0b1b")), "Ghost"),
        (434, "Stunky", _ref("core.pokeldn.sv.raid_partners.stench_f127e5b6"), ("Bite", _ref("core.pokeldn.sv.raid_partners.acid_spray_a3eb4c63"), _ref("core.pokeldn.sv.raid_partners.screech_39fa5f0a")), "Dark"),
        (281, "Kirlia", _ref("core.pokeldn.sv.raid_partners.synchronize_1600a20b"), (_ref("core.pokeldn.sv.raid_partners.confusion_9507ad17"), _ref("core.pokeldn.sv.raid_partners.calm_mind_7d5b3ef8"), _ref("core.pokeldn.sv.raid_partners.disarming_voice_d24f0358")), _ref("core.pokeldn.sv.raid_partners.psychic_2c73e325")),
        (624, "Pawniard", _ref("core.pokeldn.sv.raid_partners.defiant_9ebc1d1a"), (_ref("core.pokeldn.sv.raid_partners.metal_claw_68a70566"), _ref("core.pokeldn.sv.raid_partners.scratch_abe50eeb"), _ref("core.pokeldn.sv.raid_partners.scary_face_5e25c264")), "Steel"),
        (702, "Dedenne", _ref("core.pokeldn.sv.raid_partners.cheek_pouch_89d10697"), (_ref("core.pokeldn.sv.raid_partners.draining_kiss_28bac71b"), _ref("core.pokeldn.sv.raid_partners.parabolic_charge_8ae791c6"), "Charm"), "Fairy"),
        (402, "Kricketune", "Swarm", (_ref("core.pokeldn.sv.raid_partners.bug_bite_28a6c7de"), "Sing", _ref("core.pokeldn.sv.raid_partners.aerial_ace_4c2ce13b")), "Fairy"),
        (744, "Rockruff", _ref("core.pokeldn.sv.raid_partners.keen_eye_638cadb3"), (_ref("core.pokeldn.sv.raid_partners.rock_throw_b0d07a39"), "Bite", "Leer"), "Rock"),
        (551, "Sandile", _ref("core.pokeldn.sv.raid_partners.intimidate_7879eb29"), (_ref("core.pokeldn.sv.raid_partners.sand_tomb_a915beef"), _ref("core.pokeldn.sv.raid_partners.scary_face_5e25c264"), "Bite"), _ref("core.pokeldn.sv.raid_partners.ground_151bf493")),
        (361, "Snorunt", _ref("core.pokeldn.sv.raid_partners.inner_focus_92f27090"), (_ref("core.pokeldn.sv.raid_partners.powder_snow_59a8763c"), _ref("core.pokeldn.sv.raid_partners.ice_shard_f27b54c6"), "Bite"), "Ice"),
    ),
    40: (
        (323, "Camerupt", _ref("core.pokeldn.sv.raid_partners.magma_armor_2a4227ef"), (_ref("core.pokeldn.sv.raid_partners.flame_wheel_40e5e60e"), _ref("core.pokeldn.sv.raid_partners.bulldoze_faa824e3"), "Yawn"), "Fire"),
        (419, "Floatzel", _ref("core.pokeldn.sv.raid_partners.swift_swim_3e76a1ef"), (_ref("core.pokeldn.sv.raid_partners.water_pulse_0607361b"), _ref("core.pokeldn.sv.raid_partners.aqua_jet_0c3e802b"), "Growl"), "Water"),
        (673, "Gogoat", _ref("core.pokeldn.sv.raid_partners.sap_sipper_51734022"), (_ref("core.pokeldn.sv.raid_partners.horn_leech_dbcea9f4"), _ref("core.pokeldn.sv.raid_partners.facade_f83f6f6c"), _ref("core.pokeldn.sv.raid_partners.growth_66b06e99")), "Grass"),
        (82, "Magneton", _ref("core.pokeldn.sv.raid_partners.magnet_pull_79a510d3"), (_ref("core.pokeldn.sv.raid_partners.metal_sound_3377dbcc"), _ref("core.pokeldn.sv.raid_partners.shock_wave_a293635d"), _ref("core.pokeldn.sv.raid_partners.tri_attack_ccc77793")), _ref("core.pokeldn.sv.raid_partners.electric_a76dab2d")),
        (820, "Greedent", _ref("core.pokeldn.sv.raid_partners.cheek_pouch_89d10697"), (_ref("core.pokeldn.sv.raid_partners.facade_f83f6f6c"), "Bite", _ref("core.pokeldn.sv.raid_partners.tail_whip_1bd4075e")), _ref("core.pokeldn.sv.raid_partners.normal_a7248eeb")),
        (334, "Altaria", _ref("core.pokeldn.sv.raid_partners.natural_cure_8af0a21d"), (_ref("core.pokeldn.sv.raid_partners.aerial_ace_4c2ce13b"), _ref("core.pokeldn.sv.raid_partners.dragon_breath_3b439567"), _ref("core.pokeldn.sv.raid_partners.feather_dance_8d18b8c1")), _ref("core.pokeldn.sv.raid_partners.flying_75a4c2fe")),
        (57, "Primeape", _ref("core.pokeldn.sv.raid_partners.vital_spirit_5f36ed60"), (_ref("core.pokeldn.sv.raid_partners.low_kick_2a24e693"), _ref("core.pokeldn.sv.raid_partners.rage_fist_2dd767c4"), "Leer"), "Grass"),
        (426, "Drifblim", _ref("core.pokeldn.sv.raid_partners.aftermath_07ac3909"), ("Hex", _ref("core.pokeldn.sv.raid_partners.air_slash_723387c9"), _ref("core.pokeldn.sv.raid_partners.will_o_wisp_728d2c6e")), "Ghost"),
        (215, "Sneasel", _ref("core.pokeldn.sv.raid_partners.inner_focus_92f27090"), ("Thief", _ref("core.pokeldn.sv.raid_partners.ice_shard_f27b54c6"), "Leer"), "Ice"),
        (97, "Hypno", _ref("core.pokeldn.sv.raid_partners.insomnia_9dcefd14"), (_ref("core.pokeldn.sv.raid_partners.zen_headbutt_a65aae8c"), _ref("core.pokeldn.sv.raid_partners.fire_punch_938925a3"), _ref("core.pokeldn.sv.raid_partners.thunder_punch_01e09cc8")), _ref("core.pokeldn.sv.raid_partners.psychic_2c73e325")),
        (437, "Bronzong", _ref("core.pokeldn.sv.raid_partners.levitate_03a0beaa"), (_ref("core.pokeldn.sv.raid_partners.gyro_ball_fee5a3e0"), _ref("core.pokeldn.sv.raid_partners.psybeam_1f828fef"), _ref("core.pokeldn.sv.raid_partners.metal_sound_3377dbcc")), "Steel"),
        (700, "Sylveon", _ref("core.pokeldn.sv.raid_partners.cute_charm_f191c990"), (_ref("core.pokeldn.sv.raid_partners.fairy_wind_0a20abe5"), _ref("core.pokeldn.sv.raid_partners.quick_attack_75427c13"), "Charm"), "Fairy"),
        (123, "Scyther", "Swarm", (_ref("core.pokeldn.sv.raid_partners.fury_cutter_2f03acc1"), _ref("core.pokeldn.sv.raid_partners.aerial_ace_4c2ce13b"), "Leer"), "Fairy"),
        (745, "Lycanroc", _ref("core.pokeldn.sv.raid_partners.keen_eye_638cadb3"), (_ref("core.pokeldn.sv.raid_partners.rock_tomb_bd23c727"), _ref("core.pokeldn.sv.raid_partners.accelerock_f7e22a51"), "Leer"), "Rock"),
        (844, "Sandaconda", _ref("core.pokeldn.sv.raid_partners.sand_spit_7e7cec47"), (_ref("core.pokeldn.sv.raid_partners.bulldoze_faa824e3"), _ref("core.pokeldn.sv.raid_partners.sand_attack_53f602dc"), _ref("core.pokeldn.sv.raid_partners.poison_tail_6439ddf0")), _ref("core.pokeldn.sv.raid_partners.ground_151bf493")),
        (362, "Glalie", _ref("core.pokeldn.sv.raid_partners.inner_focus_92f27090"), (_ref("core.pokeldn.sv.raid_partners.ice_fang_2f70d85f"), "Bite", _ref("core.pokeldn.sv.raid_partners.scary_face_5e25c264")), "Ice"),
        (148, "Dragonair", _ref("core.pokeldn.sv.raid_partners.shed_skin_a61ffe3c"), (_ref("core.pokeldn.sv.raid_partners.dragon_breath_3b439567"), _ref("core.pokeldn.sv.raid_partners.safeguard_d9e41896"), "Slam"), _ref("core.pokeldn.sv.raid_partners.dragon_bbe963c6")),
        (454, "Toxicroak", _ref("core.pokeldn.sv.raid_partners.anticipation_91f4fc60"), (_ref("core.pokeldn.sv.raid_partners.venoshock_6e77e6b2"), _ref("core.pokeldn.sv.raid_partners.low_kick_2a24e693"), _ref("core.pokeldn.sv.raid_partners.poison_sting_53422879")), _ref("core.pokeldn.sv.raid_partners.poison_d5a78b99")),
    ),
    80: (
        (59, "Arcanine", _ref("core.pokeldn.sv.raid_partners.intimidate_7879eb29"), (_ref("core.pokeldn.sv.raid_partners.flamethrower_3c07f870"), "Bite", "Leer"), "Fire"),
        (748, "Toxapex", _ref("core.pokeldn.sv.raid_partners.merciless_b0d5201f"), ("Surf", _ref("core.pokeldn.sv.raid_partners.poison_jab_6bf09578"), _ref("core.pokeldn.sv.raid_partners.chilling_water_c7e73205")), "Water"),
        (930, "Arboliva", _ref("core.pokeldn.sv.raid_partners.seed_sower_e2c7e9da"), (_ref("core.pokeldn.sv.raid_partners.energy_ball_f87de401"), _ref("core.pokeldn.sv.raid_partners.safeguard_d9e41896"), _ref("core.pokeldn.sv.raid_partners.earth_power_544512e3")), "Grass"),
        (939, "Bellibolt", _ref("core.pokeldn.sv.raid_partners.electromorphosis_35587422"), (_ref("core.pokeldn.sv.raid_partners.discharge_1de69436"), _ref("core.pokeldn.sv.raid_partners.mud_shot_a31dab5f"), _ref("core.pokeldn.sv.raid_partners.light_screen_53aaa291")), _ref("core.pokeldn.sv.raid_partners.electric_a76dab2d")),
        (982, "Dudunsparce", _ref("core.pokeldn.sv.raid_partners.serene_grace_d79c258e"), (_ref("core.pokeldn.sv.raid_partners.hyper_drill_b55c549d"), "Glare", _ref("core.pokeldn.sv.raid_partners.drill_run_f8bea4d4")), _ref("core.pokeldn.sv.raid_partners.normal_a7248eeb")),
        (398, "Staraptor", _ref("core.pokeldn.sv.raid_partners.intimidate_7879eb29"), (_ref("core.pokeldn.sv.raid_partners.brave_bird_5372adcb"), _ref("core.pokeldn.sv.raid_partners.facade_f83f6f6c"), _ref("core.pokeldn.sv.raid_partners.feather_dance_8d18b8c1")), _ref("core.pokeldn.sv.raid_partners.flying_75a4c2fe")),
        (128, "Tauros", _ref("core.pokeldn.sv.raid_partners.intimidate_7879eb29"), (_ref("core.pokeldn.sv.raid_partners.raging_bull_3fb68a33"), _ref("core.pokeldn.sv.raid_partners.work_up_4735e5d6"), _ref("core.pokeldn.sv.raid_partners.assurance_9512d3fd")), "Grass"),
        (426, "Drifblim", _ref("core.pokeldn.sv.raid_partners.aftermath_07ac3909"), (_ref("core.pokeldn.sv.raid_partners.shadow_ball_fa425698"), _ref("core.pokeldn.sv.raid_partners.air_slash_723387c9"), _ref("core.pokeldn.sv.raid_partners.will_o_wisp_728d2c6e")), "Ghost"),
        (197, "Umbreon", _ref("core.pokeldn.sv.raid_partners.synchronize_1600a20b"), (_ref("core.pokeldn.sv.raid_partners.dark_pulse_06fd24d5"), _ref("core.pokeldn.sv.raid_partners.thunder_wave_96bd41f8"), _ref("core.pokeldn.sv.raid_partners.psychic_2c73e325")), "Dark"),
        (282, "Gardevoir", _ref("core.pokeldn.sv.raid_partners.synchronize_1600a20b"), (_ref("core.pokeldn.sv.raid_partners.psyshock_7eaa7268"), _ref("core.pokeldn.sv.raid_partners.dazzling_gleam_796c9bb3"), _ref("core.pokeldn.sv.raid_partners.life_dew_77d08e37")), _ref("core.pokeldn.sv.raid_partners.psychic_2c73e325")),
        (823, "Corviknight", _ref("core.pokeldn.sv.raid_partners.pressure_1f8407f9"), (_ref("core.pokeldn.sv.raid_partners.iron_head_f65e0e88"), _ref("core.pokeldn.sv.raid_partners.drill_peck_7db5a2a8"), _ref("core.pokeldn.sv.raid_partners.scary_face_5e25c264")), "Steel"),
        (700, "Sylveon", _ref("core.pokeldn.sv.raid_partners.pixilate_91385413"), (_ref("core.pokeldn.sv.raid_partners.moonblast_c0bdeeba"), _ref("core.pokeldn.sv.raid_partners.quick_attack_75427c13"), "Charm"), "Fairy"),
        (214, "Heracross", "Swarm", (_ref("core.pokeldn.sv.raid_partners.megahorn_99fb7ad1"), _ref("core.pokeldn.sv.raid_partners.brick_break_96fc8ec9"), _ref("core.pokeldn.sv.raid_partners.bulk_up_ec96b1eb")), "Bug"),
        (934, "Garganacl", _ref("core.pokeldn.sv.raid_partners.purifying_salt_70cc72d3"), (_ref("core.pokeldn.sv.raid_partners.rock_slide_854601d5"), _ref("core.pokeldn.sv.raid_partners.rock_tomb_bd23c727"), _ref("core.pokeldn.sv.raid_partners.heavy_slam_86f04d31")), "Rock"),
        (750, "Mudsdale", _ref("core.pokeldn.sv.raid_partners.own_tempo_80122d0a"), (_ref("core.pokeldn.sv.raid_partners.high_horsepower_44bdc27d"), _ref("core.pokeldn.sv.raid_partners.rock_smash_5ed98022"), _ref("core.pokeldn.sv.raid_partners.low_kick_2a24e693")), _ref("core.pokeldn.sv.raid_partners.ground_151bf493")),
        (461, "Weavile", _ref("core.pokeldn.sv.raid_partners.pressure_1f8407f9"), (_ref("core.pokeldn.sv.raid_partners.night_slash_8454100a"), _ref("core.pokeldn.sv.raid_partners.ice_punch_a24063b5"), "Leer"), "Ice"),
        (612, "Haxorus", _ref("core.pokeldn.sv.raid_partners.rivalry_43a08bd8"), (_ref("core.pokeldn.sv.raid_partners.dragon_claw_824aa6ff"), _ref("core.pokeldn.sv.raid_partners.facade_f83f6f6c"), _ref("core.pokeldn.sv.raid_partners.scary_face_5e25c264")), _ref("core.pokeldn.sv.raid_partners.dragon_bbe963c6")),
        (980, "Clodsire", _ref("core.pokeldn.sv.raid_partners.poison_point_1031e44c"), (_ref("core.pokeldn.sv.raid_partners.poison_jab_6bf09578"), _ref("core.pokeldn.sv.raid_partners.stomping_tantrum_85eba792"), "Toxic"), _ref("core.pokeldn.sv.raid_partners.ground_151bf493")),
    ),
}
# The game's pool table per stage [0.7797] and its trainers' preset level, which names the pool here.
# A partner is built at four fifths of the host Pokemon's level whatever the pool (`level_for`), so
# these are a Lv 20, 50 or 100 host's partners.
TABLES = ("raid_trainer_01", "raid_trainer_01", "raid_trainer_02", "raid_trainer_03", "raid_trainer_03")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raid_partners.json")
LEVELS = (16, 16, 40, 80, 80)

# The partners raiders want, by the pool's level: their rank (1 favoured, 2 the next tier), why, and
# why at more length (docs/sv_raid.md, Favoured partners).
RECOMMENDED = {
    80: {"Austin": (2, _ref("core.pokeldn.sv.raid_partners.intimidate_on_each_respawn_cuts_attack_a8c9f46c"),
                    _ref("core.pokeldn.sv.raid_partners.intimidate_cuts_the_boss_s_attack_on_every_respawn_leer_b9b935cd")),
         "Logan": (1, _ref("core.pokeldn.sv.raid_partners.safeguard_blocks_status_terrain_heals_b0c95d03"),
                   _ref("core.pokeldn.sv.raid_partners.safeguard_prevents_status_conditions_grassy_terrain_hea_37cc513e")),
         "Hailey": (1, _ref("core.pokeldn.sv.raid_partners.light_screen_cuts_special_damage_can_paralyze_68cb78d1"),
                    _ref("core.pokeldn.sv.raid_partners.light_screen_when_she_uses_it_cuts_the_boss_s_special_d_2b7aad94")),
         "Evan": (2, _ref("core.pokeldn.sv.raid_partners.100_accurate_glare_paralysis_buys_turns_c6c36a61"),
                  _ref("core.pokeldn.sv.raid_partners.glare_paralyzes_at_100_accuracy_except_a_boss_with_an_e_866fb019")),
         "Charlotte": (1, _ref("core.pokeldn.sv.raid_partners.intimidate_and_feather_dance_cut_attack_23255219"),
                       _ref("core.pokeldn.sv.raid_partners.intimidate_on_every_respawn_and_feather_dance_both_cut__77ef1a51")),
         "Kylie": (2, _ref("core.pokeldn.sv.raid_partners.intimidate_cuts_attack_breaks_screens_2a233ed7"),
                   _ref("core.pokeldn.sv.raid_partners.intimidate_cuts_the_boss_s_attack_on_every_respawn_ragi_e08d544c")),
         "Hunter": (2, _ref("core.pokeldn.sv.raid_partners.will_o_wisp_burn_halves_physical_damage_41578e11"),
                    _ref("core.pokeldn.sv.raid_partners.will_o_wisp_burns_the_boss_halving_the_damage_its_physi_e0af2086")),
         "Gianna": (2, _ref("core.pokeldn.sv.raid_partners.thunder_wave_paralysis_buys_free_turns_fff268d5"),
                    _ref("core.pokeldn.sv.raid_partners.thunder_wave_paralysis_can_give_a_free_turn_to_set_up_d_3e21adf9")),
         "Eli": (1, _ref("core.pokeldn.sv.raid_partners.life_dew_heals_the_whole_team_fded869e"),
                 _ref("core.pokeldn.sv.raid_partners.life_dew_heals_the_whole_team_seven_star_solo_guides_as_f01c15a5")),
         "Samantha": (2, _ref("core.pokeldn.sv.raid_partners.leer_cuts_defense_ice_punch_can_freeze_54399d67"),
                      _ref("core.pokeldn.sv.raid_partners.leer_lowers_the_boss_s_defense_before_its_shield_goes_u_6ba30a0c"))},
}


def stage_of(progress, content=_ref("core.pokeldn.sv.raid_partners.standard_fe6d3468")):
    """-> the stage a host of this raid has unlocked: its progress's, or six stars for a black crystal
    or a seven-star event raid, which only a host with six stars unlocked finds."""
    if content in ("black", "might"):
        return SIX_STARS
    return max(0, raid_encounter.PROGRESS.index(progress) - 1)


def level_for(host_level):
    """-> the level partners take beside a host Pokemon of `host_level`: int(0.8 x it), whatever the
    stage (docs/sv_raid.md, Partners)."""
    return host_level * 4 // 5


def slots(consoles=1):
    """-> the slots partners fill in a pokeldn raid `consoles` consoles join: two with one, none
    with three."""
    return max(0, HOSTED + 1 - consoles)


def pool(stage):
    """-> the partners a stage draws among, in draw order."""
    level = LEVELS[stage]
    favoured = RECOMMENDED.get(level, {})
    partners = []
    for i, (species, name, ability, moves, tera) in enumerate(POOLS[level]):
        entry = game_pool(stage)[i]
        abilities = raid_encounter.personal(entry["species"], entry["form"])[5]
        ability_id = abilities[{1: 0, 2: 1, 4: 2}[entry["ability_number"]]]
        tera_id = entry["tera"] if entry["tera"] is not None else DEFAULT_TERA[entry["species"]]
        partners.append(Partner(TRAINERS[i], entry["species"], name, level, ability, moves, tera,
                        *favoured.get(TRAINERS[i], (0, "", "")), trainer_key=str(i), form=entry["form"],
                        move_ids=tuple(entry["moves"]), ability_id=ability_id, tera_type_id=tera_id))
    return tuple(partners)


@cache
def game_pool(stage):
    """-> the game's entries of a stage's pool in draw order (scripts/gen_sv_partner_data.py): species,
    form, ability slot, move ids, Tera type (None: the species' default), gender and the fixed fields."""
    with open(DATA) as fh:
        return tuple(json.load(fh)["pools"][TABLES[stage]])


def identity(seed):
    """-> (encryption constant, TID, SID, PID, height, weight) every partner of a battle shares: draws
    0 to 4 of xoroshiro128+ from the partner seed, as the creator 0xdef2b8 makes them for a partner
    (docs/sv_raid.md, Partners)."""
    rand = raid_encounter.Xoroshiro(seed)
    ec = rand.next()
    while ec & 0xFFFFFFFF == 0xFFFFFFFF:
        ec = rand.next()
    ec &= 0xFFFFFFFF
    fake_id, pid = rand.next_int(), rand.next_int()
    shiny = (pid >> 16) ^ (pid & 0xFFFF) ^ (fake_id >> 16) ^ (fake_id & 0xFFFF)
    if shiny < 16:                      # the trainer data's NO_RARE [0xdefb2c]
        pid ^= 0x10000000
    # size class M (SizeType 3) for both, which the converter 0x160ffd0 sets [0x1611cc4]
    height, weight = 0x30 + rand.next_int(0xA0), 0x30 + rand.next_int(0xA0)
    return ec, fake_id & 0xFFFF, fake_id >> 16, pid, height, weight


def draw(seed, stage, count=HOSTED):
    """-> the indices of the trainers filling `count` empty slots, left to right: xoroshiro128+ from
    the u64 seed, each draw over the trainers still in the pool, the one drawn taken out."""
    rand = raid_encounter.Xoroshiro(seed)
    left = list(range(len(POOLS[LEVELS[stage]])))
    return [left.pop(rand.next_int(len(left))) for _ in range(count)]


def trainer(name):
    """-> a trainer's index, its name in any case."""
    if str(name).isdecimal() and 0 <= int(name) < len(TRAINERS):
        return int(name)
    for index, known in enumerate(TRAINERS):
        if known.lower() == str(name).strip().lower():
            return index
    raise ValueError(f"no raid partner is named {name!r}; the trainers are {', '.join(TRAINERS)}")


def seed_for(stage, wanted=(), entropy=os.urandom):
    """-> a random partner seed whose first draws are the trainers `wanted`, in order: none leaves
    every partner to the draw, one fixes the first."""
    wanted = tuple(wanted)
    size = len(POOLS[LEVELS[stage]])
    if len(wanted) > HOSTED:
        raise ValueError(f"a pokeldn raid seats {HOSTED} partners, not {len(wanted)}")
    if len(set(wanted)) < len(wanted):
        raise ValueError("a trainer fills one slot at most")
    for index in wanted:
        if index >= size:
            raise ValueError(f"{TRAINERS[index]} is not among the level-{LEVELS[stage]} partners")
    while True:
        seed = int.from_bytes(entropy(8), "little")
        if tuple(draw(seed, stage, len(wanted))) == wanted:
            return seed


# The species' own Tera type where an entry leaves it to the per-species table 0xe78418 reads
# (docs/sv_raid.md, Partners): Dragon for Haxorus, Ground for Clodsire.
DEFAULT_TERA = {612: 15, 980: 4}


def record_fields(seed, stage, index, level):
    """-> the gen9 fields of the partner record the console builds for pool entry `index` at `level`:
    identity(seed) and the game's entry; scale 128, language 2, met at its level, the base friendship,
    the PP of each move (35 for an empty slot)."""
    entry = game_pool(stage)[index]
    species, form = entry["species"], entry["form"]
    base, _types, _ratio, friendship, growth, abilities = raid_encounter.personal(species, form)
    ec, tid, sid, pid, height, weight = identity(seed)
    moves = tuple(entry["moves"]) + (0,) * (4 - len(entry["moves"]))
    ivs, evs = tuple(entry["ivs"]), tuple(entry["evs"])
    party = raid_encounter.stats(base, ivs, level, entry["nature"], evs)
    pp = raid_encounter.tables()["move_pp"]
    tera = entry["tera"] if entry["tera"] is not None else DEFAULT_TERA[species]
    return {
        "species": species, "form": form, "level": level, "met_level": level,
        "experience": raid_encounter.experience(level, growth), "encryption_constant": ec,
        "trainer_id": tid, "secret_id": sid, "pid": pid,
        "ability": abilities[{1: 0, 2: 1, 4: 2}[entry["ability_number"]]], "ability_number": entry["ability_number"],
        "gender": entry["gender"], "nature": entry["nature"], "stat_nature": entry["nature"], "ivs": ivs, "evs": evs,
        "height_scalar": height, "weight_scalar": weight, "scale": entry["scale"],
        "tera_type_original": tera, "tera_type_override": raid_encounter.TERA_NONE, "moves": moves,
        "move_pp": tuple(pp.get(str(mv), 35) if mv else 35 for mv in moves),
        "current_hp": party[0], "stats": party, "ot_friendship": friendship,
        "nickname": raid_encounter.tables()["species_names"][str(species)], "language": 2, "affixed_ribbon": -1,
        "ball": entry["ball"],
    }


def record(seed, stage, index, level):
    """-> the encrypted 0x158-byte party record of a partner (record_fields)."""
    from pokeldn import gen9
    return gen9.encrypt(gen9.write(bytes(gen9.SIZE_PARTY), **record_fields(seed, stage, index, level)))
