from pokeldn.app.i18n import message_ref as _message
from pokeldn.app.i18n import ref as _ref
"""Complete FRLG distributions and cartridge variants in a shared gift file. See docs/gifts.md."""

from dataclasses import dataclass
import struct
from pokeldn import gifts
from pokeldn.frlg.gift import gift_to_bin, mg_server, wonder_card
from pokeldn.frlg.gift.mystery_gift import crc16
from pokeldn.frlg.gift.stamp_rally import MysteryGiftDistribution
from pokeldn.frlg.rom import builds
from pokeldn.frlg.rom import buffer_script, scrcmd

COMPONENTS = ("card", "ram_script", "stamp", "activation_script", "install_activation_script",
              "trainer", "news", "mevent", "buffer_code")
OPTIONS = ("questionnaire", "denied_message")
# Payloads run before buffer_code in the same session, in this order: buffer_lead_1, buffer_lead_2...
MAX_LEADS = 8
LEADS = tuple(f"buffer_lead_{n}" for n in range(1, MAX_LEADS + 1))
CODE_OPTIONS = ("buffer_expect", "buffer_dump_size", "buffer_dump_blocks", "buffer_dump_address",
                "buffer_dump_addresses", "buffer_decode")


def distribution(variant):
    code = "buffer_code" in variant.data
    data = dict(variant.data)
    leads = tuple(data.pop(key) for key in LEADS if key in data)
    if any(key in variant.data for key in LEADS[len(leads):]):
        raise ValueError(_message('core.pokeldn.frlg.gift.file.console_code_leads_are_numbered_from_buffer_lead_2c03d1bf'))
    if set(data) - set(COMPONENTS) or set(variant.options) - set(CODE_OPTIONS if code else OPTIONS):
        raise ValueError(_message('core.pokeldn.frlg.gift.file.unknown_frlg_gift_component_or_option_02bc46c8'))
    if leads and not code:
        raise ValueError(_message('core.pokeldn.frlg.gift.file.console_code_leads_need_the_buffer_code_they_run_05ddb2c0'))
    if code:
        if set(data) != {"buffer_code"}:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.console_code_travels_alone_without_cards_or_gift_ea78119f'))
        for key in ("buffer_dump_size", "buffer_dump_blocks", "buffer_dump_address"):
            if key in variant.options and type(variant.options[key]) is not int:
                raise ValueError(_message('core.pokeldn.frlg.gift.file.value0_must_be_an_integer_f77ebd7b', value0=key))
        expect = variant.options.get("buffer_expect")
        if expect is not None and expect != buffer_script.EXPECT_TRAINER_ID and (
                type(expect) is not int or not 0 <= expect <= 0xffffffff):
            raise ValueError(_message('core.pokeldn.frlg.gift.file.buffer_expect_must_be_trainer_id_or_a_32_bit_uns_129142cd'))
        addresses = variant.options.get("buffer_dump_addresses", ())
        if not isinstance(addresses, tuple) or any(not 0 <= v <= 0xffffffff for v in addresses):
            raise ValueError(_message('core.pokeldn.frlg.gift.file.buffer_dump_addresses_must_contain_32_bit_unsign_639f991d'))
        address = variant.options.get("buffer_dump_address", 0)
        if not 0 <= address <= 0xffffffff:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.buffer_dump_address_must_be_a_32_bit_unsigned_in_24df55ba'))
        blocks = variant.options.get("buffer_dump_blocks", 1)
        if addresses and len(addresses) != blocks:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.a_scatter_dump_needs_one_address_per_block_9f8993b8'))
        if variant.options.get("buffer_decode") not in (None, *buffer_script.DECODED_SCRIPTS):
            raise ValueError(_message('core.pokeldn.frlg.gift.file.unknown_console_code_response_decoder_86f88927'))
        if (blocks != 1 or addresses or "buffer_decode" in variant.options) and "buffer_dump_size" not in variant.options:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.console_code_dump_options_require_buffer_dump_si_5c1c6369'))
    result = MysteryGiftDistribution(**{"card": None, "ram_script": None, "buffer_lead": leads,
                                        **data, **variant.options})
    if code:
        pass
    elif result.news is not None:
        if variant.options or set(variant.data) != {"news"}:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.wonder_news_travels_alone_without_gift_options_428dea95'))
    else:
        card = result.card
        wonder_card.flag_for_flag_id(int.from_bytes(card[:2], "little"))
        flags = card[8]
        if (flags & 3) >= 3 or ((flags >> 2) & 15) >= 8 or (flags >> 6) >= 3 or card[9] > 7:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.the_wonder_card_fails_the_game_s_field_checks_101b6e0e'))
        if not result.ram_script:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.a_wonder_card_needs_a_delivery_script_3c338cde'))
        for key in ("activation_script", "install_activation_script"):
            if (raw := getattr(result, key)) is not None and not 0 < len(raw) <= 995:
                raise ValueError(_message('core.pokeldn.frlg.gift.file.value0_must_contain_1_to_995_bytes_0106ddb4', value0=key))
        if result.questionnaire is not None and (len(result.questionnaire) != 4 or any(
                type(v) is not int or not 0 <= v <= 65535 for v in result.questionnaire)):
            raise ValueError(_message('core.pokeldn.frlg.gift.file.a_questionnaire_needs_four_16_bit_word_ids_48d374f5'))
        if result.denied_message is not None and result.questionnaire is None:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.a_refusal_message_needs_a_questionnaire_21dc0f49'))
    # The runtime also validates trainer checksums, script sizes and event termination.
    try:
        mg_server.MysteryGiftServer(**data, buffer_lead=leads, **variant.options)
    except (mg_server.MysteryGiftServerError, struct.error) as exc:
        raise ValueError(str(exc)) from exc
    return result


def validate(gift):
    if set(gift.variants) - set(builds.GAME_CODES):
        raise ValueError("FRLG variants must name supported cartridge codes: " + ", ".join(builds.GAME_CODES))
    modes = set()
    flag_ids = set()
    for code, variant in gift.variants.items():
        chosen = distribution(variant)
        japanese = builds.BUILDS[code].language == "japanese"
        for name, data, expected in (("card", chosen.card, 164 if japanese else 332),
                                     ("news", chosen.news, 224 if japanese else 444)):
            if data is not None and len(data) != expected:
                raise ValueError(_message('core.pokeldn.frlg.gift.file.value0_needs_a_value1_byte_wonder_value2_bd9b6d6a', value0=code, value1=expected, value2=name.title()))
        modes.add("code" if chosen.buffer_code is not None else "news" if chosen.is_news else "card")
        if chosen.card is not None:
            flag_ids.add(int.from_bytes(chosen.card[:2], "little"))
    if len(modes) > 1 or len(flag_ids) > 1:
        raise ValueError(_message('core.pokeldn.frlg.gift.file.frlg_variants_must_use_the_same_gift_type_and_ca_077c02ce'))


def from_payload(payload, *, console_build="auto", version=None, name=None):
    if isinstance(payload, FilePayload):
        return (gifts.Gift("frlg", name, dict(payload.file.variants)) if name else payload.file)
    from pokeldn.frlg.config import plan_builds
    plan = plan_builds(payload, console_build, version)
    candidates = plan.per_build or {code: plan.distribution for code in builds.GAME_CODES}
    if console_build != "auto":
        candidates = {console_build: plan.distribution}
    return from_distributions(name or getattr(payload, "script", getattr(payload, "gift",
                              getattr(payload, "news", _ref("core.pokeldn.frlg.gift.file.wonder_news_d58adf54")))),
                              {code: chosen for code, chosen in candidates.items()
                               if not isinstance(chosen, str)})


def from_distributions(name, per_build):
    """{game code: MysteryGiftDistribution} -> a gift file with one variant per cartridge."""
    variants = {}
    for code, chosen in per_build.items():
        data = {key: bytes(value) for key in COMPONENTS if (value := getattr(chosen, key)) is not None}
        if len(chosen.buffer_lead) > MAX_LEADS:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.a_gift_file_carries_at_most_value0_console_code__ea73747f', value0=MAX_LEADS))
        data.update(zip(LEADS, (bytes(code) for code in chosen.buffer_lead)))
        keys = CODE_OPTIONS if chosen.buffer_code is not None else OPTIONS
        options = {key: value for key in keys if (value := getattr(chosen, key)) is not None}
        variants[code] = gifts.Variant(data, options)
    return gifts.Gift("frlg", name, variants)


@dataclass(frozen=True)
class FilePayload:
    file: gifts.Gift
    definition: object = None
    dump_file: str | None = None
    requires_build_selection = True

    def __post_init__(self):
        if self.file.game != "frlg":
            raise ValueError(_message('core.pokeldn.frlg.gift.file.an_frlg_payload_needs_an_frlg_gift_file_cd4c4aff'))

    @property
    def gift(self):
        return self.file.name

    @property
    def script(self):
        return next(iter(self.file.variants.values())).options.get("buffer_decode", "imported-code")

    @property
    def expect(self):
        return next(iter(self.file.variants.values())).options.get("buffer_expect")

    @property
    def flag_id(self):
        chosen = distribution(next(iter(self.file.variants.values())))
        return int.from_bytes(chosen.card[:2], "little") if chosen.card is not None else None

    @property
    def receipt_flag(self):
        return wonder_card.flag_for_flag_id(self.flag_id)

    def build_distribution(self, build=None):
        code = (build or builds.BPRF).game_code
        if code not in self.file.variants:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.this_gift_file_has_no_value0_cartridge_variant_d135d02b', value0=code))
        return distribution(self.file.variants[code])

    def build(self, build=None):
        chosen = self.build_distribution(build)
        return chosen.card, chosen.ram_script


# A .wc3 (PKHeX's WC3 plugin, the Mystery Gift Tool, Project Pokemon's gallery): the card with its
# CRC, 0x50 bytes of save-side metadata, then the RamScript with a CRC16 over 1000 bytes (54 of 54
# gallery files), where the game sums 999 [script.c:488]. Japanese files are 0x4E4 bytes.
WC3_SIZE, WC3_JAPANESE_SIZE, WC3_SCRIPT_AT = 0x58C, 0x4E4, 0x1A0
WC3_METADATA_ICON_AT = 0x15A   # WonderCardMetadata.iconSpecies after a CRC and pad [global.h:671, mystery_gift.c:176]


def _gift(name, card, ram_script, build):
    """One variant for `build`, or for every cartridge when the script holds no absolute address."""
    if build is None:
        if pointers := scrcmd.absolute_pointers(ram_script):
            offset, command, value = pointers[0]
            raise ValueError(_message('core.pokeldn.frlg.gift.file.the_script_s_value0_at_byte_value1_points_at_0x__c375e177', value0=command, value1=offset, value2=value))
        codes = tuple(code for code, cartridge in builds.BUILDS.items()
                      if (cartridge.language == "japanese") == (len(card) == 164))
    else:
        cartridge = builds.resolve(build)
        if (cartridge.language == "japanese") != (len(card) == 164):
            raise ValueError(_message('core.pokeldn.frlg.gift.file.the_card_format_does_not_match_this_cartridge_la_30ac381a'))
        codes = (cartridge.game_code,)
    gift = gifts.Gift("frlg", name, {code: gifts.Variant({"card": bytes(card),
                                                          "ram_script": bytes(ram_script)})
                                     for code in codes})
    distribution(gift.variants[codes[0]])
    return gift


def _unbound(script):
    if script[4:8] != bytes((51, 255, 255, 255)):
        raise ValueError(_message('core.pokeldn.frlg.gift.file.the_script_is_not_an_unbound_mystery_gift_delive_6b1d1493'))
    return script[8:1003]


def from_bins(card, script, *, build=None, name="FRLG gift"):
    if len(card) not in (gift_to_bin.WONDER_CARD_BIN_SIZE, 168) or len(script) != gift_to_bin.SCRIPT_BIN_SIZE:
        raise ValueError(_message('core.pokeldn.frlg.gift.file.frlg_import_needs_a_168_or_336_byte_wondercard_b_7f533e5e'))
    if int.from_bytes(card[:2], "little") != crc16(card[4:]):
        raise ValueError(_message('core.pokeldn.frlg.gift.file.wondercard_bin_checksum_failed_7bafbf6d'))
    # The game's CRC covers the pad byte too (docs/frlg_gift.md, The one RAM script slot); older
    # exports covered 999 bytes.
    if int.from_bytes(script[:2], "little") not in (crc16(script[4:1004]), crc16(script[4:1003])):
        raise ValueError(_message('core.pokeldn.frlg.gift.file.script_bin_checksum_failed_e585bd91'))
    return _gift(name, card[4:], _unbound(script), build)


def from_wc3(raw, *, build=None, name="FRLG gift"):
    if len(raw) not in (WC3_SIZE, WC3_JAPANESE_SIZE):
        raise ValueError(_message('core.pokeldn.frlg.gift.file.a_wc3_has_1420_or_1252_bytes_this_file_has_value_97526806', value0=len(raw)))
    japanese = len(raw) == WC3_JAPANESE_SIZE
    card_size, script_at = (168, 0xF8) if japanese else (gift_to_bin.WONDER_CARD_BIN_SIZE, WC3_SCRIPT_AT)
    card, script = raw[:card_size], raw[script_at:]
    if int.from_bytes(card[:2], "little") != crc16(card[4:]):
        raise ValueError(_message('core.pokeldn.frlg.gift.file.the_wc3_card_checksum_failed_e2e05744'))
    if int.from_bytes(script[:2], "little") not in (crc16(script[4:1004]), crc16(script[4:1003])):
        raise ValueError(_message('core.pokeldn.frlg.gift.file.the_wc3_script_checksum_failed_9620fe7f'))
    return _gift(name, card[4:], _unbound(script), build)


def with_icon(gift, species):
    """The gift with every variant's card showing `species`' icon; 0 shows none. Above 411 the game
    draws the question mark [mystery_gift_show_card.c:466, pokemon_icon.c:1102]."""
    from pokeldn.frlg.gift.gift_composer import MAX_POKEMON_SPECIES
    if type(species) is not int or not 0 <= species <= MAX_POKEMON_SPECIES:
        raise ValueError(_message('core.pokeldn.frlg.gift.file.a_card_icon_is_a_species_from_0_to_value0_e3943d1b', value0=MAX_POKEMON_SPECIES))
    variants = {}
    for code, variant in gift.variants.items():
        card = variant.data.get("card")
        if card is None:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.only_a_wonder_card_has_an_icon_a503ecf2'))
        variants[code] = gifts.Variant({**variant.data, "card": card[:2] + species.to_bytes(2, "little")
                                        + card[4:]}, dict(variant.options))
    return gifts.Gift(gift.game, gift.name, variants)


def from_code(code, *, build, name=_ref("core.pokeldn.frlg.gift.file.console_code_33f04c21"), expect=None, dump_size=None):
    options = {}
    if expect is not None:
        options["buffer_expect"] = expect
    if dump_size is not None:
        options["buffer_dump_size"] = dump_size
    return gifts.Gift("frlg", name, {build: gifts.Variant({"buffer_code": bytes(code)}, options)})


def _native(gift, build, what):
    """The one card and script a native file holds; without `build`, variants must carry the same bytes."""
    if build is None:
        if len({(v.data.get("card"), v.data.get("ram_script")) for v in gift.variants.values()}) != 1:
            raise ValueError(_message('core.pokeldn.frlg.gift.file.this_gift_differs_per_cartridge_choose_build_for_2e74a03c'))
        build = next(iter(gift.variants))
    if build not in gift.variants:
        raise ValueError(_message('core.pokeldn.frlg.gift.file.this_gift_has_no_value0_variant_1e7f98b8', value0=build))
    chosen = distribution(gift.variants[build])
    if chosen.buffer_code is not None:
        raise ValueError(_message('core.pokeldn.frlg.gift.file.value0_cannot_preserve_console_code_and_its_resp_46cd2b66', value0=what))
    if chosen.is_news or chosen.is_stamp or chosen.has_trainer or chosen.has_mevent or chosen.is_gated:
        raise ValueError(_message('core.pokeldn.frlg.gift.file.value0_cannot_preserve_this_gift_s_extras_use_po_75e951e5', value0=what))
    return chosen


def export_native(gift, directory, *, build=None):
    chosen = _native(gift, build, "The two-file native format")
    return gift_to_bin.write_gift_bins(directory, "Gift", chosen.card, chosen.ram_script)


def to_wc3(gift, *, build=None):
    """-> an international or Japanese .wc3; metadata is zero but for the card's icon."""
    chosen = _native(gift, build, "A .wc3")
    metadata = bytearray(80)
    icon = 10
    metadata[icon:icon + 2] = chosen.card[2:4]
    return (gift_to_bin.build_wonder_card_bin(chosen.card) + bytes(metadata)
            + gift_to_bin.build_script_bin(chosen.ram_script))
