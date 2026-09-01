"""Command-line player for a world."""

import argparse
import pathlib
import sys

from engine import data
from engine.state import new_game
from engine.verbs import describe, perform
from engine.world import WorldError, load

CONTENT = pathlib.Path(__file__).resolve().parents[1] / "content"


class UsageError(Exception):
    """Raised when the command line asks for something the world does not offer."""


def main(argv=None):
    """Load the world named on the command line and play it."""
    arguments = _arguments(argv)
    named = _world(arguments.world)
    if named is None:
        print(_said("no_such_world", name=arguments.world,
                    worlds=", ".join(_worlds())), file=sys.stderr)
        return 1
    try:
        world = load(named)
        posture = _posture(world, arguments.defend)
        commands = _script(arguments.script)
        transcript = _transcript(arguments.transcript)
    except (WorldError, UsageError, OSError) as refused:
        print(str(refused), file=sys.stderr)
        return 1
    try:
        _play(world, commands, transcript, posture)
    except KeyboardInterrupt:
        return 130
    finally:
        if transcript:
            transcript.close()
    return 0


def _arguments(argv):
    """Parse the command line."""
    parser = argparse.ArgumentParser(description="Play a world.")
    parser.add_argument("world", help="a world in content/, or a path to one")
    parser.add_argument("--script", help="read commands from this file instead of stdin")
    parser.add_argument("--transcript", help="append everything printed to this file")
    parser.add_argument("--defend", help="defence posture: 'all', or comma-separated "
                        "defence names the world declares")
    return parser.parse_args(argv)


def _posture(world, spec):
    """Return the set of defence flags named, or raise UsageError with a CLI line."""
    declared = world.get("defences", {})
    if spec is None:
        return set()
    if not declared:
        raise UsageError(_said("no_defences", world=world["meta"]["title"]))
    names = [part.strip() for part in spec.split(",") if part.strip()]
    if not names:
        raise UsageError(_said("empty_posture", defences=", ".join(declared)))
    if "all" in names:
        return set(declared)
    for name in names:
        if name not in declared:
            raise UsageError(_said("no_such_defence", name=name, world=world["meta"]["title"],
                                   defences=", ".join(declared)))
    return set(names)


def _world(named):
    given = pathlib.Path(named)
    if given.is_dir():
        return given
    beside = CONTENT / named
    return beside if beside.is_dir() else None


def _worlds():
    return sorted(world.name for world in CONTENT.iterdir() if world.is_dir())


def _said(line, **fields):
    return data.read(data.RULES, "reports")["cli"][line].format(**fields)


def _script(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        return [line.rstrip("\n") for line in handle]


def _transcript(path):
    return open(path, "a", encoding="utf-8") if path else None


def _play(world, commands, transcript, posture=None):
    posture = posture or set()
    game = new_game(world, posture)
    prompt = world["words"]["messages"]["player"]["prompt"]
    _say(world["meta"]["title"], transcript)
    _say("", transcript)
    if posture:
        names = ", ".join(world["defences"][flag]["label"] for flag in world["defences"]
                          if flag in posture)
        _say(world["words"]["messages"]["player"]["posture_active"].format(names=names),
             transcript)
        _say("", transcript)
    _say(describe(world, game), transcript)
    pending = None if commands is None else list(commands)
    while not game["over"]:
        command = _read(prompt, pending, transcript)
        if command is None:
            return
        here = game["location"]
        result = perform(world, game, command)
        # TODO clears on load, doesn't on look. should be the engine saying "described"
        if game["location"] != here and sys.stdout.isatty():
            print("\033[2J\033[H", end="")
        if result:
            _say(result, transcript)


def _read(prompt, pending, transcript):
    if pending is None:
        print(prompt, end="", flush=True)
        try:
            command = input()
        except EOFError:
            return None
        _write(transcript, prompt + command)
        return command
    if not pending:
        return None
    command = pending.pop(0)
    _say(prompt + command, transcript)
    return command


def _say(text, transcript):
    print(text)
    _write(transcript, text)


def _write(transcript, text):
    if transcript:
        transcript.write(text + "\n")


if __name__ == "__main__":
    sys.exit(main())
