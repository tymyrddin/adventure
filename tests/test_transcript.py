"""The scripted walkthrough reproduces the committed transcript byte for byte."""

import json
import pathlib
import tomllib

import pytest

from cli.play import main
from engine import data
from engine.state import content_hash, new_game, restore, save
from engine.verbs import describe, perform
from engine.world import StateError, WorldError, load, validate
from tests.conftest import ROOT, lay_out, said

ORIGINAL = ROOT / "content" / "original"
OT = ROOT / "content" / "ot"
GOLDEN = pathlib.Path(__file__).parent / "golden"


def run(tmp_path, name):
    produced = tmp_path / name
    status = main([str(lay_out(tmp_path)),
                   "--script", str(GOLDEN / "walkthrough.script"),
                   "--transcript", str(produced)])
    assert status == 0
    return produced.read_bytes()


def started(tmp_path):
    """Return a copy of the sample world as a directory, and a fresh game on it."""
    world = load(lay_out(tmp_path))
    return world, new_game(world)


def test_golden(tmp_path, capsys):
    produced = run(tmp_path, "walkthrough.transcript")
    assert produced == (GOLDEN / "walkthrough.transcript").read_bytes()
    assert capsys.readouterr().out.encode() == produced


def test_defended():
    """A posture flag makes its action refuse with the blocked text; off, it fires."""
    world = load(OT)
    disabled = new_game(world, {"def_sis"})
    disabled["location"] = "hunt"
    disabled["flags"].update({"creds_known"})
    refused = perform(world, disabled, "disable safety")
    assert "safety_off" not in disabled["flags"]
    assert refused == world["actions"]["disable_safety"]["blocked"]
    allowed = new_game(world)
    allowed["location"] = "hunt"
    allowed["flags"].update({"creds_known"})
    perform(world, allowed, "disable safety")
    assert "safety_off" in allowed["flags"]


def test_defended_needs_conditions():
    """Before the action's own conditions hold, a posture changes nothing."""
    world = load(OT)
    game = new_game(world, {"def_sis"})
    game["location"] = "hunt"
    assert perform(world, game, "disable safety") == said(world, "no_effect")


def test_blocked_raises():
    """A refusal with blocked_raises leaves marks, and can be tried again at that price."""
    world = load(OT)
    game = new_game(world, {"def_alarm_watched"})
    game["location"] = "reach"
    for attempt in (1, 2):
        assert perform(world, game, "probe boundary box") == \
            world["actions"]["probe_boundary"]["blocked"]
        assert game["marks"] == {"exposure": 40 * attempt}
    assert "alarm_raised" not in game["flags"]
    assert "probe_boundary" not in game["fired"]


def test_help_defended():
    world = load(OT)
    game = new_game(world, {"def_sis"})
    game["location"] = "hunt"
    game["flags"].add("creds_known")
    assert "disable: safety" in perform(world, game, "help")


WITH_DEFENCE = (
    '[meta]\ntitle = "T"\nstart = "hall"\nversion = 1\nending = "rung"\n\n'
    '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\noneway = true\n'
    'things = ["bell"]\n\n'
    '[things.bell]\nname = "bell"\n\n'
    '[actions.ring]\nverb = "ring"\nnoun = "bell"\nsets = ["rung"]\n'
    'unless = ["def_hush"]\nblocked = "It will not ring."\nmessage = "Ding."\n\n'
    '[defences.def_hush]\nlabel = "a hush over the hall"\n')


def test_load_posture(tmp_path):
    world = load(lay_out(tmp_path, WITH_DEFENCE))
    plain = new_game(world)
    perform(world, plain, "save")
    defended = new_game(world, {"def_hush"})
    perform(world, defended, "load")
    assert "def_hush" in defended["flags"]
    assert perform(world, defended, "ring bell") == "It will not ring."
    perform(world, defended, "save")
    plain = new_game(world)
    perform(world, plain, "load")
    assert "def_hush" not in plain["flags"]


def test_posture_line(tmp_path):
    where = lay_out(tmp_path, WITH_DEFENCE)
    produced = tmp_path / "out.transcript"
    script = tmp_path / "script"
    script.write_text("ring bell\n")
    assert main([str(where), "--defend", "def_hush", "--script", str(script),
                 "--transcript", str(produced)]) == 0
    lines = produced.read_text().split("\n")
    assert lines[2] == "In place now: a hush over the hall."
    assert "It will not ring." in lines


def test_bad_posture(tmp_path, capsys):
    where = lay_out(tmp_path, WITH_DEFENCE)
    produced = tmp_path / "out.transcript"
    for spec in (" , ", "def_nothing"):
        assert main([str(where), "--defend", spec, "--transcript", str(produced)]) == 1
        assert not produced.exists()
    assert main([str(where), "--defend", "all,def_nothing", "--script", "/dev/null"]) == 0
    said_so = capsys.readouterr()
    assert "choose from: def_hush" in said_so.err
    assert "no defence called def_nothing" in said_so.err


def test_go_phrase():
    """`go` plus the exit as listed moves the player, articles or not."""
    world = load(OT)
    walked = new_game(world)
    perform(world, walked, "begin")
    typed = new_game(world)
    perform(world, typed, "begin")
    perform(world, walked, "access laptop")
    perform(world, typed, "go access the laptop")
    assert typed["location"] == walked["location"] != "before"
    assert perform(world, typed, "go to the moon") == said(world, "no_way", dir="to moon")


def test_deterministic(tmp_path, capsys):
    assert run(tmp_path, "first.transcript") == run(tmp_path, "second.transcript")
    capsys.readouterr()


def test_exit_one(tmp_path, capsys):
    refused = lay_out(tmp_path, (GOLDEN.parent / "worlds" / "start_missing.toml").read_text())
    assert main([str(refused)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "start room void does not exist"


@pytest.mark.parametrize("flag,named", [("--script", "nowhere.txt"),
                                       ("--transcript", "nowhere/t.txt")])
def test_bad_file(flag, named, tmp_path, capsys):
    assert main([str(lay_out(tmp_path)), flag, str(tmp_path / named)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "nowhere" in captured.err


def test_interrupt(tmp_path, monkeypatch, capsys):
    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupted)
    assert main([str(lay_out(tmp_path))]) == 130
    capsys.readouterr()


def test_by_name(tmp_path, capsys):
    script = tmp_path / "quit.script"
    script.write_text("quit\n")
    assert main(["original", "--script", str(script)]) == 0
    assert capsys.readouterr().out.startswith(load(ORIGINAL)["meta"]["title"])


def test_unknown_world(capsys):
    """The refusal lists the worlds that exist, rather than echoing a path that does not."""
    assert main(["nowhere"]) == 1
    refused = capsys.readouterr().err
    assert "nowhere" in refused
    for name in ("original", "ot"):
        assert name in refused


ENDING = ('[meta]\ntitle = "E"\nstart = "hall"\nversion = 1\n'
          'ending = "rung"\n\n'
          '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\n'
          'oneway = true\nthings = ["bell"]\n\n'
          '[things.bell]\nname = "bell"\nportable = true\n\n'
          '[actions.ring_bell]\nverb = "ring"\nnoun = "bell"\n'
          'sets = ["rung"]\nmessage = "It rings, and that is that."\n')


def test_ending(tmp_path):
    world = load(lay_out(tmp_path, ENDING))
    game = new_game(world)
    assert not game["over"]
    assert perform(world, game, "ring bell") == world["actions"]["ring_bell"]["message"]
    assert game["over"]


def test_no_ending(tmp_path):
    """A world that names no ending is over only when the player says so."""
    world, game = started(tmp_path)
    for command in ("take lamp", "light lamp", "in", "dig rubble", "down"):
        perform(world, game, command)
    assert not game["over"]


MARKED = ('[meta]\ntitle = "M"\nstart = "hall"\nversion = 1\n'
          'ending = "watched"\n\n'
          '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\n'
          'oneway = true\nthings = ["token", "panel"]\n\n'
          '[things.token]\nname = "token"\nportable = true\n\n'
          '[things.panel]\nname = "panel"\n\n'
          '[marks.attention]\nthreshold = 3\nsets = "watched"\n\n'
          '[actions.tap_panel]\nverb = "tap"\nnoun = "panel"\n'
          'sets = ["tapped"]\nonce = false\nraises = { attention = 1 }\n'
          'message = "Tapped."\n\n'
          '[actions.redeem_token]\nverb = "redeem"\nnoun = "token"\n'
          'needs = ["token"]\nspends = ["token"]\nsets = ["redeemed"]\n'
          'raises = { attention = 2 }\nmessage = "Spent."\n')


def test_mark(tmp_path):
    """What a move leaves behind accumulates quietly until a threshold is reached."""
    world = load(lay_out(tmp_path, MARKED))
    game = new_game(world)
    perform(world, game, "tap panel")
    assert game["marks"] == {"attention": 1}
    assert game["flags"] == {"tapped"}
    assert not game["over"]


def test_threshold(tmp_path):
    world = load(lay_out(tmp_path, MARKED))
    game = new_game(world)
    for _ in range(3):
        perform(world, game, "tap panel")
    assert game["marks"]["attention"] == 3
    assert "watched" in game["flags"]
    assert game["over"]


def test_prices(tmp_path):
    world = load(lay_out(tmp_path, MARKED))
    game = new_game(world)
    perform(world, game, "take token")
    perform(world, game, "redeem token")
    assert game["marks"]["attention"] == 2


def test_spends(tmp_path):
    world = load(lay_out(tmp_path, MARKED))
    game = new_game(world)
    perform(world, game, "take token")
    assert "token" in game["inventory"]
    assert perform(world, game, "redeem token") == "Spent."
    assert "token" not in game["inventory"]
    assert perform(world, game, "redeem token") == said(world, "no_such_thing",
                                                        noun="token")


def test_no_marks(tmp_path):
    """Worlds that price nothing carry no counts at all."""
    world, game = started(tmp_path)
    for command in ("take lamp", "light lamp", "in"):
        perform(world, game, command)
    assert game["marks"] == {}


SHUTS = ('[meta]\ntitle = "S"\nstart = "office"\nversion = 1\n\n'
         '[rooms.office]\nname = "Office"\ndesc = "An office."\n'
         'exits = { through = "plant" }\nunless = { through = "noticed" }\n'
         'things = ["panel"]\n\n'
         '[rooms.plant]\nname = "Plant"\ndesc = "A plant."\n'
         'exits = { back = "office" }\n\n'
         '[things.panel]\nname = "panel"\n\n'
         '[marks.disruption]\nthreshold = 1\nsets = "noticed"\n\n'
         '[actions.tap]\nverb = "tap"\nnoun = "panel"\nonce = false\n'
         'sets = ["tapped"]\nraises = { disruption = 1 }\nmessage = "Tap."\n')


def test_shuts(tmp_path):
    world = load(lay_out(tmp_path, SHUTS))
    game = new_game(world)
    assert perform(world, game, "through").startswith(world["rooms"]["plant"]["name"])
    perform(world, game, "back")
    perform(world, game, "tap panel")
    assert "noticed" in game["flags"]
    assert perform(world, game, "through") == said(world, "shut", dir="through")
    assert game["location"] == "office"


def test_shut_line(tmp_path):
    world = load(lay_out(tmp_path, SHUTS))
    game = new_game(world)
    perform(world, game, "tap panel")
    answer = perform(world, game, "through")
    assert answer == said(world, "shut", dir="through")
    assert answer != said(world, "blocked", dir="through")


def test_shut_warning(tmp_path):
    words = data.load(lay_out(tmp_path, name="plain"))
    _errors, warnings = validate(tomllib.loads(SHUTS), words)
    assert any("the way through can shut once noticed" in line for line in warnings)


BOTH_GATES = ('[meta]\ntitle = "G"\nstart = "fork"\nversion = 1\n\n'
              '[rooms.fork]\nname = "Fork"\ndesc = "A fork."\n'
              'exits = { quiet = "kept", loud = "seen" }\n'
              'requires = { loud = "tripped" }\nunless = { quiet = "tripped" }\n'
              'things = ["switch"]\n\n'
              '[rooms.kept]\nname = "Kept"\ndesc = "Quiet."\nexits = { back = "fork" }\n\n'
              '[rooms.seen]\nname = "Seen"\ndesc = "Loud."\nexits = { back = "fork" }\n\n'
              '[things.switch]\nname = "switch"\n\n'
              '[actions.flip]\nverb = "flip"\nnoun = "switch"\n'
              'sets = ["tripped"]\nmessage = "Flipped."\n')


def test_hidden(tmp_path):
    """A hidden exit stays off the exits and help lists until it is genuinely passable."""
    world = load(lay_out(tmp_path, BOTH_GATES))
    game = new_game(world)
    world["rooms"]["fork"]["hidden"] = ["loud"]
    assert "loud" not in perform(world, game, "look")
    assert "loud" not in perform(world, game, "help")
    perform(world, game, "flip switch")
    assert "loud" in perform(world, game, "look")
    assert "loud" in perform(world, game, "help")


def test_shut_and_open(tmp_path):
    world = load(lay_out(tmp_path, BOTH_GATES))
    game = new_game(world)
    assert perform(world, game, "quiet").startswith(world["rooms"]["kept"]["name"])
    perform(world, game, "back")
    assert perform(world, game, "loud") == said(world, "blocked", dir="loud")
    perform(world, game, "flip switch")
    assert perform(world, game, "quiet") == said(world, "shut", dir="quiet")
    assert perform(world, game, "loud").startswith(world["rooms"]["seen"]["name"])


THROWN = ('[meta]\ntitle = "T"\nstart = "office"\nversion = 1\n\n'
          '[rooms.office]\nname = "Office"\ndesc = "An office."\n'
          'exits = { in = "server_room" }\n\n'
          '[rooms.server_room]\nname = "Server room"\ndesc = "Racks."\n'
          'exits = { out = "office" }\nthings = ["console"]\n\n'
          '[things.console]\nname = "console"\n\n'
          '[actions.probe]\nverb = "probe"\nnoun = "console"\n'
          'goes = "office"\nsets = ["noticed"]\nmessage = "Escorted out."\n')


def test_goes(tmp_path):
    world = load(lay_out(tmp_path, THROWN))
    game = new_game(world)
    perform(world, game, "in")
    answer = perform(world, game, "probe console")
    assert game["location"] == "office"
    assert "noticed" in game["flags"]
    assert answer == "Escorted out.\n" + describe(world, game)


def test_stays(tmp_path):
    """Without goes, the reply is the message alone, as it always was."""
    world = load(lay_out(tmp_path, THROWN))
    game = new_game(world)
    del world["actions"]["probe"]["goes"]
    perform(world, game, "in")
    assert perform(world, game, "probe console") == "Escorted out."
    assert game["location"] == "server_room"


def test_describe(tmp_path):
    world, game = started(tmp_path)
    assert describe(world, game).startswith("Cave mouth\n\n")
    assert game["moves"] == 0


def test_quit(tmp_path):
    """The quit verb marks the game over rather than leaving clients to read the reply."""
    world, game = started(tmp_path)
    assert not game["over"]
    assert perform(world, game, "quit") == said(world, "goodbye")
    assert game["over"]


def test_save(tmp_path):
    """A saved game restores the location, inventory, flags and placements."""
    world, game = started(tmp_path)
    for command in ("take lamp", "light lamp", "in"):
        perform(world, game, command)
    assert perform(world, game, "save") == said(world, "saved")
    expected = {key: value for key, value in game.items() if key != "posture"}
    assert restore(tmp_path / "world" / "save.json", content_hash(game["source"]),
                   world["words"]["messages"]["player"]) == expected


def test_restore_other_world(tmp_path):
    world, game = started(tmp_path)
    save(game, tmp_path / "world" / "save.json")
    (tmp_path / "world" / "world.toml").write_text("[meta]\ntitle = 'Other'\n")
    with pytest.raises(StateError) as refused:
        restore(tmp_path / "world" / "save.json", content_hash(game["source"]),
                world["words"]["messages"]["player"])
    assert str(refused.value) == said(world, "save_mismatch")


def test_restore_missing(tmp_path):
    words = data.load(lay_out(tmp_path))["messages"]["player"]
    with pytest.raises(StateError) as refused:
        restore(tmp_path / "world" / "save.json", "any-hash", words)
    assert str(refused.value) == words["save_missing"]


@pytest.mark.parametrize("payload", [
    {}, {"game": []}, {"game": {"flags": 1}},
    {"game": {"location": "cave_mouth", "inventory": [], "flags": "abc", "fired": [],
              "moves": 0, "marks": {}, "placements": {}, "over": False}}
])
def test_restore_shape(payload, tmp_path):
    """A file that parses as JSON but is not a save is refused, not half applied."""
    world, game = started(tmp_path)
    path = tmp_path / "world" / "save.json"
    path.write_text(json.dumps(dict(payload, world_hash=content_hash(game["source"]))))
    with pytest.raises(StateError) as refused:
        restore(path, content_hash(game["source"]),
                world["words"]["messages"]["player"])
    assert str(refused.value) == said(world, "save_mismatch")


def test_no_handler(tmp_path):
    """A world adding a verb the engine cannot run is told so, rather than crashing."""
    world = lay_out(tmp_path)
    (world / "builtins.toml").write_text("[verbs.shout]\nneeds_noun = false\n")
    loaded = load(world)
    game = new_game(loaded)
    assert perform(loaded, game, "shout") == said(loaded, "unknown_verb", word="shout")
    assert game["moves"] == 0


def test_handlers(tmp_path):
    world, game = started(tmp_path)
    builtins = world["words"]["builtins"]
    for verb in list(builtins["verbs"]) + list(builtins["abbreviations"]):
        assert perform(world, game, verb) != f"Unknown verb: {verb}."


def test_bare_verb(tmp_path):
    """A sentence the parser could not finish is not a puzzle refusing to open."""
    world, game = started(tmp_path)
    for verb in ("examine", "take", "drop", "dig"):
        assert perform(world, game, verb) == said(world, "needs_noun",
                                                  verb=verb.capitalize())
    assert perform(world, game, "go") == said(world, "needs_direction", verb="Go")


def test_requires(tmp_path):
    world, game = started(tmp_path)
    perform(world, game, "in")
    assert perform(world, game, "down") == said(world, "blocked", dir="down")
    for command in ("out", "take shovel", "in", "dig rubble"):
        perform(world, game, command)
    assert perform(world, game, "down").startswith(world["rooms"]["grotto"]["name"])


def test_not_portable(tmp_path):
    """Scenery answers with its own refusal and is still in the room afterwards."""
    world, game = started(tmp_path)
    for command in ("take lamp", "light lamp", "in"):
        perform(world, game, command)
    assert perform(world, game, "take rubble") == said(world, "not_portable")
    assert "rubble" in game["placements"]["debris_room"]
    assert "rubble" not in game["inventory"]


def test_once(tmp_path):
    world, game = started(tmp_path)
    perform(world, game, "take lamp")
    assert perform(world, game, "light lamp") == \
        world["actions"]["light_lamp"]["message"]
    assert perform(world, game, "light lamp") == said(world, "already_done")
    assert game["flags"] == {"lamp_lit"}


def test_no_effect(tmp_path):
    world, game = started(tmp_path)
    perform(world, game, "take lamp")
    assert perform(world, game, "take lamp") == said(world, "no_effect")
    assert perform(world, game, "drop shovel") == said(world, "no_effect")
    for command in ("light lamp", "in"):
        perform(world, game, command)
    assert perform(world, game, "dig rubble") == said(world, "no_effect")


HELD = ('[meta]\ntitle = "H"\nstart = "hall"\nversion = 1\n\n'
        '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\n'
        'exits = { north = "vault" }\nholding = { north = "ring" }\n'
        'things = ["ring"]\n\n'
        '[rooms.vault]\nname = "Vault"\ndesc = "A vault."\n'
        'exits = { south = "hall" }\n\n'
        '[things.ring]\nname = "Ring"\nportable = true\n')


def test_holding(tmp_path):
    loaded = load(lay_out(tmp_path, HELD))
    game = new_game(loaded)
    assert perform(loaded, game, "north") == said(loaded, "blocked", dir="north")
    assert perform(loaded, game, "take ring") == said(loaded, "taken")
    assert perform(loaded, game, "north").startswith(loaded["rooms"]["vault"]["name"])
    perform(loaded, game, "south")
    perform(loaded, game, "drop ring")
    assert perform(loaded, game, "north") == said(loaded, "blocked", dir="north")


def test_holding_solvable(tmp_path):
    assert "vault" in load(lay_out(tmp_path, HELD))["rooms"]


def test_noun_join(tmp_path):
    loaded = load(lay_out(tmp_path, '[meta]\ntitle = "K"\nstart = "vault"\nversion = 1\n\n'
                     '[rooms.vault]\nname = "Vault"\ndesc = "A vault."\n'
                     'oneway = true\nthings = ["gold_key"]\n\n'
                     '[things.gold_key]\nname = "Gold key"\nportable = true\n'))
    game = new_game(loaded)
    assert perform(loaded, game, "take gold key") == said(loaded, "taken")
    assert perform(loaded, game, "inventory") == said(
        loaded, "carrying", things=loaded["things"]["gold_key"]["name"])


TWO_BRASS = ('[meta]\ntitle = "T"\nstart = "hall"\nversion = 1\n\n'
             '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\n'
             'oneway = true\nthings = ["brass_lamp", "brass_bell"]\n\n'
             '[things.brass_lamp]\nname = "brass lamp"\nportable = true\n\n'
             '[things.brass_bell]\nname = "brass bell"\nportable = true\n')


def test_unknown_noun(tmp_path):
    world, game = started(tmp_path)
    assert perform(world, game, "take iron key") == said(
        world, "no_such_thing", noun="iron key")


def test_name_typed(tmp_path):
    world, game = started(tmp_path)
    assert perform(world, game, "take brass lamp") == said(world, "taken")
    assert "lamp" in game["inventory"]


def test_one_word(tmp_path):
    loaded = load(lay_out(tmp_path, HELD))
    game = new_game(loaded)
    assert perform(loaded, game, "take ring") == said(loaded, "taken")
    assert "ring" in game["inventory"]


def test_which_one(tmp_path):
    """Where the words fit more than one thing here, the game asks rather than guesses."""
    world = load(lay_out(tmp_path, TWO_BRASS))
    game = new_game(world)
    answer = perform(world, game, "take brass")
    assert answer == said(world, "which_one", things="brass lamp, brass bell")
    assert game["inventory"] == []


def test_direction_not_thing(tmp_path):
    world, game = started(tmp_path)
    for command in ("take lamp", "light lamp"):
        perform(world, game, command)
    assert perform(world, game, "go in").startswith(
        world["rooms"]["debris_room"]["name"])


def test_help(tmp_path):
    world, game = started(tmp_path)
    assert perform(world, game, "help") == (
        "Ways out: in.\n"
        "take: lamp, shovel.\n"
        "examine: lamp, shovel.\n"
        "light: lamp.\n"
        "Always: look, inventory, save, load, quit, help.\n"
        "Short forms: l for look, i for inventory.")


def test_help_carried(tmp_path):
    world, game = started(tmp_path)
    perform(world, game, "take lamp")
    said = perform(world, game, "help")
    assert "take: shovel." in said
    assert "drop: lamp." in said


def test_help_verbs(tmp_path):
    world, game = started(tmp_path)
    perform(world, game, "take lamp")
    assert "light: lamp." in perform(world, game, "help")
    perform(world, game, "drop lamp")
    perform(world, game, "in")
    assert "light" not in perform(world, game, "help")


def test_help_dark(tmp_path):
    world, game = started(tmp_path)
    perform(world, game, "in")
    said = perform(world, game, "help")
    assert said.startswith("Ways out: out, down.")
    assert "take:" not in said
    assert "examine:" not in said


def test_load_missing(tmp_path):
    """The load verb returns the message rather than raising at the player."""
    world, game = started(tmp_path)
    assert perform(world, game, "load") == said(world, "save_missing")


def test_unsaid(tmp_path):
    world = lay_out(tmp_path)
    (world / "messages.toml").unlink()
    with pytest.raises(WorldError) as refused:
        load(world)
    assert "world says nothing for:" in str(refused.value)


def test_unsaid_one(tmp_path):
    world = lay_out(tmp_path)
    said_lines = (world / "messages.toml").read_text()
    (world / "messages.toml").write_text(
        said_lines.replace('goodbye = "Goodbye."\n', ""))
    with pytest.raises(WorldError) as refused:
        load(world)
    assert "goodbye" in str(refused.value)


def test_two_worlds():
    cave, other = load(ORIGINAL), load(OT)
    digging = new_game(cave)
    for step in ("begin",):
        perform(cave, digging, step)
    assert perform(cave, digging, "take brass lamp") == said(cave, "taken")
    walking = new_game(other)
    for step in ("begin", "access laptop"):
        perform(other, walking, step)
    assert perform(other, walking, "inventory") == said(other, "carrying_nothing")
    assert said(other, "carrying_nothing") != said(cave, "carrying_nothing")
    assert said(other, "pitch_dark") != said(cave, "pitch_dark")
    for world in (cave, other):
        assert set(world["words"]["schema"]["said"]) <= set(
            world["words"]["messages"]["player"])
    assert cave["words"]["messages"] != other["words"]["messages"]
