# Adventures

[![CI](https://github.com/tymyrddin/adventure/actions/workflows/ci.yml/badge.svg)](https://github.com/tymyrddin/adventure/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Code licence: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![Worlds licence: CC BY 4.0](https://img.shields.io/badge/worlds-CC%20BY%204.0-blue.svg)](content/LICENCE)

A text adventure engine in the tradition of Colossal Cave and Zork. You type what you want to do, the game describes
what happens, and the world keeps track of the consequences.

Four worlds are currently included. Each has its own short introduction:

* `original`: [The Old Working](content/original/README.md), a cave adventure. You go under a hill and work out how
  things fit together.
* `ot`: [I Promise I'm a Qualified Engineer](content/ot/README.md), an evening at a water treatment plant, played from
  the wrong side of the desk.
* `network`: [I Promise the Route Is Good](content/network/README.md), the machinery under the internet, and a lie that
  keeps working.
* `cloud`: [I Promise I Belong Here](content/cloud/README.md), a shared cloud tenant read for months while every
  dashboard reports a calm and blameless year.

The non-original worlds let you inhabit an attacker's decisions on a particular terrain. They show reasoning and
consequence; they do not teach techniques.

## Playing

From the repository root:

```text
./play original
./play ot
./play network
./play cloud
```

You can also pass a world directory directly:

```text
python -m cli.play content/original
```

An unrecognised world name lists the available worlds.

Type `begin` to start. From there, use the basic vocabulary (check in `help`). `help` is contextual. It tells you what 
you can do where you are. The available actions can change as the game progresses, so `help` is a useful move when you 
are stuck.

## Worlds

A world is a directory containing two files:

```text
world.toml
messages.toml
```

`world.toml` contains the structure and rules of the world: rooms, objects, exits and actions.

`messages.toml` contains the texts presented to a player.

A world can define:

* rooms and exits
* portable objects
* flags recording things that have happened
* exits gated by remembered flags or objects currently held
* exits that close when a particular flag is set
* actions that move the player somewhere else when they fire
* dark rooms that require a light source to be described
* `marks`, which accumulate as the player acts and can set flags at thresholds
* `spends`, which consume objects when they are used
* an ending, reached when the world records the required state

`marks` provide a simple way to model accumulating consequences. An action can increase several marks at once.
Crossing a threshold can change the available world.

The `rules/` directory contains the parts shared by every world: built-in verbs, the content schema, and the vocabulary
used by the authoring tools. The tooling's language is kept separate from the messages shown to players.

## Authoring and expanding

The repository includes a map editor. It displays a world as a graph and provides an editor for each room, including:

* name and description
* exits and their conditions
* darkness
* objects
* actions

Marks and the ending are configured at world level.

The editor works with names and readable flags. Saves are validated before being
written using atomic writes, so the editor does not leave behind a world that the engine cannot load.

Start it with:

```text
.venv/bin/flask --app "editor.app:create_app('content/ot')" run --debug
```

The editor is intended as a local, single-author tool. There is no authentication.

The TOML files are also designed to be readable and editable by hand.

## Setup

The project uses Python 3.12.

The engine and CLI use only the standard library. The editor adds Flask and tomlkit.

Create a virtual environment and install the development dependencies:

```text
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Commands are run from the repository root.

## Tests

Run the main checks with:

```text
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy
```

The test suite is primarily concerned with behaviour. Room descriptions can be rewritten without
changing the tests. The suite checks things such as:

* gates opening and closing under the right conditions
* marks crossing their thresholds
* actions firing once
* objects being consumed correctly
* the parser resolving player commands
* invalid world data being rejected

The golden transcript is the exception. It exercises a complete game and checks the resulting output byte for
byte. Regenerating it is therefore an explicit change, not something the test suite does automatically.

The world used by the transcript lives with the tests, so changes to authored worlds do not
alter the behavioural fixture.

There is also a browser harness under `tools/harness/`. It drives the actual map editor in a real browser, covering the
JavaScript that is not exercised by the Python tests. It requires Node and a browser. If either is unavailable, the
browser harness is skipped.

## Layout

```text
content/   worlds: original, ot, network, cloud (each with its own README)
rules/     shared built-ins, schema and authoring vocabulary
engine/    world loading, validation, state, data and verbs
cli/       command line player and ./play launcher
editor/    map editor, writer, templates and static assets
tests/     behavioural tests, validators, transcript and fixtures
tools/     browser harness
```

If you are looking at the engine, start with `engine/verbs.py`.

The client interface is deliberately small:

```text
perform(world, game, line)
describe(world, game)
```

`perform` takes a world, the current game state and a player command, and returns the resulting output.

`describe` returns the player's current view of the world.

The `world` is the authored content and rules. It does not change during play.

The `game` is the mutable state: location, inventory, remembered flags and the contents of rooms.

That separation is the core of the engine. A client needs the world and the current game state. Everything else is
implementation detail.

## Intent

The central idea behind non-original worlds is simple: a useful move can open several possibilities; a costly move
can leave the player somewhere less useful; and a defensive response can close one route while making another more
interesting.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the three checks that CI runs, and the conventions this repository
keeps.

## Licence

This repository is licensed in two parts. The engine and tooling are under the [MIT Licence](LICENSE). The authored
worlds under `content/`, being creative content rather than code, are under [Creative Commons Attribution
4.0](content/LICENCE). Both let you build on the work with attribution; the split simply lets the code and the worlds
be reused on their own terms.
