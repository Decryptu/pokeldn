"""The GUI and CLI use the launchers' own gift builders. See docs/gifts.md."""

from pokeldn import gifts, pokemon
from pokeldn.app import command
from pokeldn.app.introspect import _load

GAMES = {"frlg-gift": "frlg", "frlg-code": "frlg", "swsh-gift": "swsh"}


def _invalid_options(message):
    raise ValueError(message)


def read(tool, path):
    gift = gifts.load(path, game=GAMES[tool.key])
    if gift.game == "frlg":
        is_code = "buffer_code" in next(iter(gift.variants.values())).data
        if is_code != (tool.key == "frlg-code"):
            raise ValueError("Choose Console code for ARM payloads or Mystery Gift for cards and news.")
    return gift


def build(tool, values, extra, settings):
    game = GAMES[tool.key]
    module = _load(tool.script)
    parser = module.build_parser()
    parser.error = _invalid_options
    try:
        args = parser.parse_args(command.build(tool, values, extra, settings))
        if game == "frlg":
            from pokeldn.frlg.gift.file import from_payload
            if args.gift_file:
                read(tool, args.gift_file)
            config = module.build_run_config(parser, args)
            return from_payload(config.payload, console_build=config.console_build,
                                version=config.console_version)
        from pokeldn.swsh.gift_file import from_record
        record = module.build_record(args)
        pokemon.SERVICE.validate_gift(record)
        if args.record and not args.patch:
            return read(tool, args.record)
        return from_record(record, name=args.nickname or "Sword/Shield gift")
    except SystemExit as exc:
        raise ValueError("The gift options are invalid; check the launcher options.") from exc
