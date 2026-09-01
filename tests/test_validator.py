"""The validator reports the error and warning lines verbatim."""

import tomllib

import pytest

from engine.world import WorldError, load, validate
from tests.conftest import RULES, SAMPLE, WORLDS, broken, lay_out

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
    ("also_unknown_flag.toml", "hall: also when phantom, which nothing ever sets"),
    ("note_unknown_flag.toml", "hall: note when phantom, which nothing ever sets"),
    ("action_unless_unknown_flag.toml",
     "action ring: unless phantom, which nothing ever sets"),
    ("unless_needs_blocked.toml", "action ring: a defence in unless, but no blocked text"),
    ("reason_bad.toml", "hall: the reason for out is not text"),
    ("bad_threshold.toml",
     "mark attention: threshold is 0; it must be more than nothing")
]


def errors_for(name, words):
    with open(WORLDS / name, "rb") as handle:
        return validate(tomllib.load(handle), words)[0]


@pytest.mark.parametrize("name,line", CASES)
def test_error(name, line, words):
    """Each broken world produces the error line, byte for byte."""
    assert line in errors_for(name, words)


@pytest.mark.parametrize("name,line", CASES)
def test_load_refuses(name, line, tmp_path):
    with pytest.raises(WorldError) as caught:
        load(broken(tmp_path, name))
    assert line in str(caught.value).split("\n")


def test_also(words):
    world = tomllib.loads(
        '[meta]\ntitle = "T"\nstart = "hall"\nversion = 1\nending = "seen"\n\n'
        '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\nexits = { north = "cellar" }\n\n'
        '[[rooms.hall.also]]\nwhen = "seen"\ndesc = "A hall gone strange."\n\n'
        '[[rooms.hall.notes]]\nwhen = "seen"\nline = "A bell was rung here."\n\n'
        '[rooms.cellar]\nname = "Cellar"\ndesc = "A cellar."\n'
        'exits = { south = "hall" }\nthings = ["bell"]\n\n'
        '[things.bell]\nname = "bell"\n\n'
        '[actions.ring]\nverb = "ring"\nnoun = "bell"\nsets = ["seen"]\nmessage = "Ding."\n')
    assert validate(world, words)[0] == []


def test_defence(words):
    """A declared defence, named by an action's unless with blocked text, validates."""
    world = tomllib.loads(
        '[meta]\ntitle = "T"\nstart = "hall"\nversion = 1\nending = "rung"\n\n'
        '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\noneway = true\n'
        'things = ["bell"]\n\n'
        '[things.bell]\nname = "bell"\n\n'
        '[actions.ring]\nverb = "ring"\nnoun = "bell"\nsets = ["rung"]\n'
        'unless = ["def_hush"]\nblocked = "It will not ring."\nmessage = "Ding."\n\n'
        '[defences.def_hush]\nlabel = "a hush over the hall"\n')
    assert validate(world, words)[0] == []


def test_reason_ungated(words):
    """Text nothing would ever say is reported, and the world still loads."""
    world = tomllib.loads(
        '[meta]\ntitle = "T"\nstart = "hall"\nversion = 1\n\n'
        '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\nexits = { out = "yard" }\n'
        'reasons = { out = "Not yet." }\n\n'
        '[rooms.yard]\nname = "Yard"\ndesc = "A yard."\nexits = { in = "hall" }\n')
    errors, warnings = validate(world, words)
    assert errors == []
    assert warnings == ["hall: a reason for out, but nothing gates it"]


def test_unless_requires(words):
    """A flag set only to close another action is not reported as never required."""
    world = tomllib.loads(
        '[meta]\ntitle = "T"\nstart = "hall"\nversion = 1\nending = "rung"\n\n'
        '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\noneway = true\n'
        'things = ["bell", "rope"]\n\n'
        '[things.bell]\nname = "bell"\n\n[things.rope]\nname = "rope"\n\n'
        '[actions.cut]\nverb = "cut"\nnoun = "rope"\nsets = ["cut"]\nmessage = "Cut."\n\n'
        '[actions.ring]\nverb = "ring"\nnoun = "bell"\nsets = ["rung"]\n'
        'unless = ["cut"]\nmessage = "Ding."\n')
    assert validate(world, words) == ([], [])


def test_bad_words_file(tmp_path):
    """A syntax error in messages.toml says which file, not just a line and column."""
    where = lay_out(tmp_path)
    with open(where / "messages.toml", "a", encoding="utf-8") as handle:
        handle.write("\nthis is = = not toml\n")
    with pytest.raises(WorldError) as caught:
        load(where)
    assert "messages.toml" in str(caught.value)


def test_unparsable(tmp_path):
    with pytest.raises(WorldError):
        load(broken(tmp_path, "malformed.toml"))


def test_missing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(WorldError):
        load(empty)


def test_sample(words):
    with open(SAMPLE, "rb") as handle:
        errors, warnings = validate(tomllib.load(handle), words)
    assert errors == []
    assert warnings == []


def test_builtins():
    with open(BUILTINS, "rb") as handle:
        builtins = tomllib.load(handle)
    assert builtins == {
        "articles": ["a", "an", "the"],
        "verbs": {
            "look": {},
            "go": {"needs_noun": True, "takes_direction": True},
            "take": {"needs_noun": True, "dark_blocks": True},
            "drop": {"needs_noun": True},
            "examine": {"needs_noun": True, "dark_blocks": True},
            "inventory": {},
            "save": {},
            "load": {},
            "quit": {},
            "help": {}
        },
        "abbreviations": {"l": "look", "i": "inventory"},
        "directions": {"n": "north", "s": "south", "e": "east",
                       "w": "west", "u": "up", "d": "down"},
        "opposites": {"north": "south", "south": "north", "east": "west",
                      "west": "east", "up": "down", "down": "up",
                      "in": "out", "out": "in"},
        "offsets": {"north": [0, -1], "south": [0, 1],
                    "east": [1, 0], "west": [-1, 0]},
        "files": {"world": "world.toml", "save": "save.json"}
    }


def test_opposites():
    with open(BUILTINS, "rb") as handle:
        opposites = tomllib.load(handle)["opposites"]
    for direction, opposite in opposites.items():
        assert opposites[opposite] == direction


def test_synonyms(words):
    """Every built-in verb and abbreviation is accepted as a synonym target."""
    with open(BUILTINS, "rb") as handle:
        builtins = tomllib.load(handle)
    targets = list(builtins["verbs"]) + list(builtins["abbreviations"])
    world = {
        "meta": {"title": "Syn", "start": "hall", "version": 1},
        "rooms": {"hall": {"name": "Hall", "desc": "A hall.", "oneway": True}},
        "synonyms": {f"w{index}": target for index, target in enumerate(targets)}
    }
    assert validate(world, words)[0] == []


def test_warnings(words):
    world = {
        "meta": {"title": "Warn", "start": "hall", "version": 1},
        "rooms": {"hall": {"name": "Hall", "desc": "A hall."}},
        "things": {"lamp": {"name": "brass lamp"}},
        "actions": {"open_door": {"verb": "open", "noun": "lamp",
                                  "sets": ["opened"], "message": "Open."}}
    }
    assert validate(world, words)[1] == [
        "hall: no exits and not marked oneway",
        "thing lamp: defined but never placed and never needed",
        "flag opened: set by open_door but never required"
    ]
