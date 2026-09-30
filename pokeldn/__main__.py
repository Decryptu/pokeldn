"""Run the same tool presets as the desktop app."""
import argparse
import os

from pokeldn.app import catalog, command, runner, settings
from pokeldn.pokemon import BuilderError


def main(argv=None):
    tools = {tool.key: tool for game in catalog.GAMES for tool in game.tools}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list available tools")
    parser.add_argument("--radio", help="radio backend, e.g. esp32:auto")
    parser.add_argument("tool", nargs="?", choices=tuple(tools))
    parser.add_argument("args", nargs=argparse.REMAINDER, help="arguments passed to the tool")
    args = parser.parse_args(argv)
    if args.list:
        for game in catalog.GAMES:
            for tool in game.tools:
                print(f"{tool.key:20} {game.name}: {tool.name}")
        return 0
    if not args.tool:
        parser.print_help()
        return 0
    profile = settings.load()
    if args.radio:
        os.environ["POKELDN_RADIO"] = args.radio
    tool = tools[args.tool]
    overrides = args.args[1:] if args.args[:1] == ["--"] else args.args
    try:
        runner.child(["--run", tool.script, *command.build(tool, {}, {}, profile), *overrides])
    except BuilderError as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
