"""The gift a tool would send, as a .pokegift: built gifts compile directly, a preset sent as flags goes
through the launcher's own builder. See docs/gifts.md."""

from pokeldn.app import command, gift_builder
from pokeldn.app.introspect import _load


def _invalid_options(message):
    raise ValueError(message)


def build(tool, values, extra, settings):
    field = next(f for f in tool.fields if f.kind == "builder")
    value = gift_builder.normalized(gift_builder.GAMES[tool.key], command.value_of(field, values))
    flags = gift_builder.args(tool, value)
    if "--gift-file" in flags:
        return gift_builder.compile(tool, value)
    module = _load(tool.script)
    parser = module.build_parser()
    parser.error = _invalid_options
    from pokeldn.frlg.gift.file import from_payload
    try:
        args = parser.parse_args(command.build(tool, values, extra, settings))
        config = module.build_run_config(parser, args)
    except SystemExit as exc:
        raise ValueError("The gift options are invalid; check the launcher options.") from exc
    preset = gift_builder.module("frlg").PRESET[value["preset"]]
    return from_payload(config.payload, console_build=config.console_build,
                        version=config.console_version, name=preset.label)
