"""Command-line player for a world."""

import argparse
import pathlib
import sys

from engine import data
from engine.state import new_game
from engine.verbs import describe, perform
from engine.world import WorldError, load

CONTENT = pathlib.Path(__file__).resolve().parents[1] / "content"


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
        commands = _script(arguments.script)
        transcript = _transcript(arguments.transcript)
    except (WorldError, OSError) as refused:
        print(str(refused), file=sys.stderr)
        return 1
    try:
        _play(world, commands, transcript)
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
    return parser.parse_args(argv)


def _world(named):
    """Return the directory a name or a path stands for, or None when there is none."""
    given = pathlib.Path(named)
    if given.is_dir():
        return given
    beside = CONTENT / named
    return beside if beside.is_dir() else None


def _worlds():
    """Return the names of the worlds that ship with the game, in alphabetical order."""
    return sorted(world.name for world in CONTENT.iterdir() if world.is_dir())


def _said(line, **fields):
    """Return one line the command line says for itself."""
    return data.read(data.RULES, "reports")["cli"][line].format(**fields)


def _script(path):
    """Return the commands in the script file, or None to read from stdin."""
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        return [line.rstrip("\n") for line in handle]


def _transcript(path):
    """Return the file everything printed is appended to, or None when there is none."""
    return open(path, "a", encoding="utf-8") if path else None


def _play(world, commands, transcript):
    """Print the opening, then run the loop until the game ends or the input does."""
    game = new_game(world)
    prompt = world["words"]["messages"]["player"]["prompt"]
    _say(world["meta"]["title"], transcript)
    _say("", transcript)
    _say(describe(world, game), transcript)
    pending = None if commands is None else list(commands)
    while not game["over"]:
        command = _read(prompt, pending, transcript)
        if command is None:
            return
        result = perform(world, game, command)
        if result:
            _say(result, transcript)


def _read(prompt, pending, transcript):
    """Return the next command after its prompt, or None when the input ends."""
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
    """Print a line and record it in the transcript."""
    print(text)
    _write(transcript, text)


def _write(transcript, text):
    """Append one line to the transcript, when there is one."""
    if transcript:
        transcript.write(text + "\n")


if __name__ == "__main__":
    sys.exit(main())
