"""Complete FRLG distributions and cartridge variants in a shared gift file. See docs/gifts.md."""

from dataclasses import dataclass
import struct
from pokeldn import gifts
from pokeldn.frlg.gift import gift_to_bin, mg_server, wonder_card, wonder_news
from pokeldn.frlg.gift.mystery_gift import crc16
from pokeldn.frlg.gift.stamp_rally import MysteryGiftDistribution
from pokeldn.frlg.rom import builds
from pokeldn.frlg.rom import buffer_script

COMPONENTS = ("card", "ram_script", "stamp", "activation_script", "install_activation_script",
              "trainer", "news", "mevent", "buffer_code")
OPTIONS = ("questionnaire", "denied_message")
CODE_OPTIONS = ("buffer_expect", "buffer_dump_size", "buffer_dump_blocks", "buffer_dump_address",
                "buffer_dump_addresses", "buffer_decode")


def distribution(variant):
    code = "buffer_code" in variant.data
    if set(variant.data) - set(COMPONENTS) or set(variant.options) - set(CODE_OPTIONS if code else OPTIONS):
        raise ValueError("Unknown FRLG gift component or option.")
    if code:
        if set(variant.data) != {"buffer_code"}:
            raise ValueError("Console code travels alone, without cards or gift scripts.")
        for key in ("buffer_dump_size", "buffer_dump_blocks", "buffer_dump_address"):
            if key in variant.options and type(variant.options[key]) is not int:
                raise ValueError(f"{key} must be an integer.")
        expect = variant.options.get("buffer_expect")
        if expect is not None and expect != buffer_script.EXPECT_TRAINER_ID and (
                type(expect) is not int or not 0 <= expect <= 0xffffffff):
            raise ValueError("buffer_expect must be trainer-id or a 32-bit unsigned integer.")
        addresses = variant.options.get("buffer_dump_addresses", ())
        if not isinstance(addresses, tuple) or any(not 0 <= v <= 0xffffffff for v in addresses):
            raise ValueError("buffer_dump_addresses must contain 32-bit unsigned integers.")
        address = variant.options.get("buffer_dump_address", 0)
        if not 0 <= address <= 0xffffffff:
            raise ValueError("buffer_dump_address must be a 32-bit unsigned integer.")
        blocks = variant.options.get("buffer_dump_blocks", 1)
        if addresses and len(addresses) != blocks:
            raise ValueError("A scatter dump needs one address per block.")
        if variant.options.get("buffer_decode") not in (None, *buffer_script.DECODED_SCRIPTS):
            raise ValueError("Unknown console-code response decoder.")
        if (blocks != 1 or addresses or "buffer_decode" in variant.options) and "buffer_dump_size" not in variant.options:
            raise ValueError("Console-code dump options require buffer_dump_size.")
    result = MysteryGiftDistribution(**{"card": None, "ram_script": None,
                                        **variant.data, **variant.options})
    if code:
        pass
    elif result.news is not None:
        if variant.options or set(variant.data) != {"news"}:
            raise ValueError("Wonder News travels alone, without gift options.")
    else:
        card = result.card
        wonder_card.flag_for_flag_id(int.from_bytes(card[:2], "little"))
        flags = card[8]
        if (flags & 3) >= 3 or ((flags >> 2) & 15) >= 8 or (flags >> 6) >= 3 or card[9] > 7:
            raise ValueError("The Wonder Card fails the game's field checks.")
        if not result.ram_script:
            raise ValueError("A Wonder Card needs a delivery script.")
        for key in ("activation_script", "install_activation_script"):
            if (raw := getattr(result, key)) is not None and not 0 < len(raw) <= 995:
                raise ValueError(f"{key} must contain 1 to 995 bytes.")
        if result.questionnaire is not None and (len(result.questionnaire) != 4 or any(
                type(v) is not int or not 0 <= v <= 65535 for v in result.questionnaire)):
            raise ValueError("A questionnaire needs four 16-bit word IDs.")
        if result.denied_message is not None and result.questionnaire is None:
            raise ValueError("A refusal message needs a questionnaire.")
    # The runtime also validates trainer checksums, script sizes and event termination.
    try:
        mg_server.MysteryGiftServer(**variant.data, **variant.options)
    except (mg_server.MysteryGiftServerError, struct.error) as exc:
        raise ValueError(str(exc)) from exc
    return result


def validate(gift):
    if set(gift.variants) - set(builds.GAME_CODES):
        raise ValueError("FRLG variants must name supported cartridge codes: " + ", ".join(builds.GAME_CODES))
    modes = set()
    flag_ids = set()
    for variant in gift.variants.values():
        chosen = distribution(variant)
        modes.add("code" if chosen.buffer_code is not None else "news" if chosen.is_news else "card")
        if chosen.card is not None:
            flag_ids.add(int.from_bytes(chosen.card[:2], "little"))
    if len(modes) > 1 or len(flag_ids) > 1:
        raise ValueError("FRLG variants must use the same gift type and card flag ID.")


def from_payload(payload, *, console_build="auto", version=None, name=None):
    if isinstance(payload, FilePayload):
        return (gifts.Gift("frlg", name, dict(payload.file.variants)) if name else payload.file)
    from pokeldn.frlg.config import plan_builds
    plan = plan_builds(payload, console_build, version)
    candidates = plan.per_build or {code: plan.distribution for code in builds.GAME_CODES}
    if console_build != "auto":
        candidates = {console_build: plan.distribution}
    return from_distributions(name or getattr(payload, "script", getattr(payload, "gift",
                              getattr(payload, "news", "Wonder News"))),
                              {code: chosen for code, chosen in candidates.items()
                               if not isinstance(chosen, str)})


def from_distributions(name, per_build):
    """{game code: MysteryGiftDistribution} -> a gift file with one variant per cartridge."""
    variants = {}
    for code, chosen in per_build.items():
        data = {key: bytes(value) for key in COMPONENTS if (value := getattr(chosen, key)) is not None}
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
            raise ValueError("An FRLG payload needs an FRLG gift file.")

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
            raise ValueError(f"This gift file has no {code} cartridge variant.")
        return distribution(self.file.variants[code])

    def build(self, build=None):
        chosen = self.build_distribution(build)
        return chosen.card, chosen.ram_script


def from_bins(card, script, *, build, name="FRLG gift"):
    if len(card) != gift_to_bin.WONDER_CARD_BIN_SIZE or len(script) != gift_to_bin.SCRIPT_BIN_SIZE:
        raise ValueError("FRLG import needs a 336-byte WonderCard.bin and a 1004-byte Script.bin.")
    if int.from_bytes(card[:2], "little") != crc16(card[4:]):
        raise ValueError("WonderCard.bin checksum failed.")
    if int.from_bytes(script[:2], "little") != crc16(script[4:1003]):
        raise ValueError("Script.bin checksum failed.")
    if script[4:8] != bytes((51, 255, 255, 255)):
        raise ValueError("Script.bin is not an unbound Mystery Gift delivery script.")
    return gifts.Gift("frlg", name, {build: gifts.Variant({"card": bytes(card[4:]),
                                                         "ram_script": bytes(script[8:1003])})})


def from_code(code, *, build, name="Console code", expect=None, dump_size=None):
    options = {}
    if expect is not None:
        options["buffer_expect"] = expect
    if dump_size is not None:
        options["buffer_dump_size"] = dump_size
    return gifts.Gift("frlg", name, {build: gifts.Variant({"buffer_code": bytes(code)}, options)})


def export_native(gift, directory, *, build=None):
    if build is None:
        if len(gift.variants) != 1:
            raise ValueError("Choose --build for a gift with several cartridge variants.")
        build = next(iter(gift.variants))
    if build not in gift.variants:
        raise ValueError(f"This gift has no {build} variant.")
    chosen = distribution(gift.variants[build])
    if chosen.buffer_code is not None:
        raise ValueError("Native gift files cannot preserve console code and its response settings; use .pokegift.")
    if chosen.is_news or chosen.is_stamp or chosen.has_trainer or chosen.has_mevent or chosen.is_gated:
        raise ValueError("The two-file native format cannot preserve this gift's extras; use .pokegift.")
    return gift_to_bin.write_gift_bins(directory, "Gift", chosen.card, chosen.ram_script)
