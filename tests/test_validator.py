"""The validator reports the error and warning lines verbatim."""

import tomllib

import pytest

from engine.world import WorldError, load, validate
from tests.conftest import RULES, SAMPLE, WORLDS, broken

BUILTINS = RULES / "builtins.toml"

# One minimal broken world per error the validator can report.
CASES = [
    ("exit_unknown_room.toml", "hall: exit north leads to unknown room nowhere"),
    ("room_unknown_thing.toml", "hall: unknown thing ghost"),
    ("requires_without_exit.toml", "hall: requires on south, but no exit south"),
    ("hidden_without_exit.toml", "hall: hidden lists south, but no exit south"),
    ("requires_unknown_flag.toml", "hall: requires flag opened which no action sets"),
    ("thing_placed_twice.toml", "thing lamp placed in more than one room"),
    ("action_unknown_room.toml", "action open_door: unknown room cellar"),
    ("goes_unknown_room.toml", "action open_door: goes to unknown room cellar"),
    ("action_unknown_thing.toml", "action wave_ghost: unknown thing ghost"),
    ("action_empty_sets.toml", "action open_door: empty sets"),
    ("duplicate_verb_noun.toml",
     "actions open_door and unlock_door: duplicate verb-noun pair open door"),
    ("synonym_unknown_target.toml", "synonym g: unknown target grok"),
    ("unknown_key.toml", "unknown key colour in rooms.hall"),
    ("start_missing.toml", "start room void does not exist"),
    ("unreachable.toml", "unreachable rooms: cellar"),
    ("bad_version.toml", "meta.version is 2; only 1 is supported"),
    ("unknown_table.toml", "unknown key npcs in world"),
    ("missing_key.toml", "missing key desc in rooms.hall"),
    ("bad_value.toml", "bad value for dark in rooms.hall"),
    ("bad_id.toml", "bad id Cave-Mouth in rooms"),
    ("ending_unknown_flag.toml",
     "meta.ending is nowhere, which no action sets"),
    ("action_unknown_mark.toml", "action ring_bell: unknown mark attention"),
    ("unless_without_exit.toml", "hall: unless on south, but no exit south"),
    ("unless_unknown_flag.toml", "hall: unless flag phantom which nothing ever sets"),
    ("bad_threshold.toml",
     "mark attention: threshold is 0; it must be more than nothing"),
]


def errors_for(name, words):
    """Return the error lines for one of the broken worlds."""
    with open(WORLDS / name, "rb") as handle:
        return validate(tomllib.load(handle), words)[0]


@pytest.mark.parametrize("name,line", CASES)
def test_error_line(name, line, words):
    """Each broken world produces the error line, byte for byte."""
    assert line in errors_for(name, words)


@pytest.mark.parametrize("name,line", CASES)
def test_load_refuses_and_joins(name, line, tmp_path):
    """load raises WorldError carrying every error line, newline joined."""
    with pytest.raises(WorldError) as caught:
        load(broken(tmp_path, name))
    assert line in str(caught.value).split("\n")


def test_unparsable_file_is_a_world_error(tmp_path):
    """A TOML syntax error reaches the caller as WorldError, not a decoder exception."""
    with pytest.raises(WorldError):
        load(broken(tmp_path, "malformed.toml"))


def test_missing_world_file_is_a_world_error(tmp_path):
    """A directory with no world file is refused the same way, not as an OSError."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(WorldError):
        load(empty)


def test_sample_world_is_clean(words):
    """The sample world validates with no errors and no warnings."""
    with open(SAMPLE, "rb") as handle:
        errors, warnings = validate(tomllib.load(handle), words)
    assert errors == []
    assert warnings == []


def test_builtin_vocabulary():
    """The data file carries the fixed vocabulary and nothing else."""
    with open(BUILTINS, "rb") as handle:
        builtins = tomllib.load(handle)
    assert builtins == {
        "articles": ["a", "an", "the"],
        "verbs": {
            "look": {"dark_blocks": True},
            "go": {"needs_noun": True, "takes_direction": True},
            "take": {"needs_noun": True, "dark_blocks": True},
            "drop": {"needs_noun": True},
            "examine": {"needs_noun": True, "dark_blocks": True},
            "inventory": {},
            "save": {},
            "load": {},
            "quit": {},
            "help": {},
        },
        "abbreviations": {"l": "look", "i": "inventory"},
        "directions": {"n": "north", "s": "south", "e": "east",
                       "w": "west", "u": "up", "d": "down"},
        "opposites": {"north": "south", "south": "north", "east": "west",
                      "west": "east", "up": "down", "down": "up",
                      "in": "out", "out": "in"},
        "offsets": {"north": [0, -1], "south": [0, 1],
                    "east": [1, 0], "west": [-1, 0]},
        "files": {"world": "world.toml", "save": "save.json"},
    }


def test_direction_opposites_pair_up():
    """Every opposite is itself opposed by the direction it names."""
    with open(BUILTINS, "rb") as handle:
        opposites = tomllib.load(handle)["opposites"]
    for direction, opposite in opposites.items():
        assert opposites[opposite] == direction


def test_synonyms_may_target_any_builtin(words):
    """Every built-in verb and abbreviation is accepted as a synonym target."""
    with open(BUILTINS, "rb") as handle:
        builtins = tomllib.load(handle)
    targets = list(builtins["verbs"]) + list(builtins["abbreviations"])
    world = {
        "meta": {"title": "Syn", "start": "hall", "version": 1},
        "rooms": {"hall": {"name": "Hall", "desc": "A hall.", "oneway": True}},
        "synonyms": {f"w{index}": target for index, target in enumerate(targets)},
    }
    assert validate(world, words)[0] == []


def test_warning_lines(words):
    """A room without exits, an unused thing and an unrequired flag each warn."""
    world = {
        "meta": {"title": "Warn", "start": "hall", "version": 1},
        "rooms": {"hall": {"name": "Hall", "desc": "A hall."}},
        "things": {"lamp": {"name": "brass lamp"}},
        "actions": {"open_door": {"verb": "open", "noun": "lamp",
                                  "sets": ["opened"], "message": "Open."}},
    }
    assert validate(world, words)[1] == [
        "hall: no exits and not marked oneway",
        "thing lamp: defined but never placed and never needed",
        "flag opened: set by open_door but never required",
    ]
