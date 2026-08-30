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
    """Play the walkthrough script, returning the transcript it wrote."""
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


def test_walkthrough_matches_the_golden_transcript(tmp_path, capsys):
    """The transcript file and stdout both equal the committed bytes."""
    produced = run(tmp_path, "walkthrough.transcript")
    assert produced == (GOLDEN / "walkthrough.transcript").read_bytes()
    assert capsys.readouterr().out.encode() == produced


def test_two_runs_are_identical(tmp_path, capsys):
    """The same world and the same script produce the same bytes every time."""
    assert run(tmp_path, "first.transcript") == run(tmp_path, "second.transcript")
    capsys.readouterr()


def test_refused_world_exits_one(tmp_path, capsys):
    """A world that fails validation prints its errors to stderr and exits 1."""
    refused = lay_out(tmp_path, (GOLDEN.parent / "worlds" / "start_missing.toml").read_text())
    assert main([str(refused)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "start room void does not exist"


@pytest.mark.parametrize("flag,named", [("--script", "nowhere.txt"),
                                       ("--transcript", "nowhere/t.txt")])
def test_a_file_the_player_named_is_reported_not_raised(flag, named, tmp_path, capsys):
    """A script or transcript that cannot be opened exits one, as a refused world does."""
    assert main([str(lay_out(tmp_path)), flag, str(tmp_path / named)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "nowhere" in captured.err


def test_an_interrupted_game_exits_without_a_traceback(tmp_path, monkeypatch, capsys):
    """Ctrl-C at the prompt leaves by the conventional code, not by a stack trace."""
    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupted)
    assert main([str(lay_out(tmp_path))]) == 130
    capsys.readouterr()


def test_a_world_can_be_named_instead_of_pointed_at(tmp_path, capsys):
    """A bare name resolves to content/, so the path need not be typed out."""
    script = tmp_path / "quit.script"
    script.write_text("quit\n")
    assert main(["original", "--script", str(script)]) == 0
    assert capsys.readouterr().out.startswith(load(ORIGINAL)["meta"]["title"])


def test_an_unknown_world_names_the_ones_there_are(capsys):
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


def test_a_world_ends_when_it_says_it_does(tmp_path):
    """The game is over the moment the world remembers what it named as its ending."""
    world = load(lay_out(tmp_path, ENDING))
    game = new_game(world)
    assert not game["over"]
    assert perform(world, game, "ring bell") == world["actions"]["ring_bell"]["message"]
    assert game["over"]


def test_a_world_without_an_ending_runs_on(tmp_path):
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


def test_a_mark_rises_without_crossing_anything(tmp_path):
    """What a move leaves behind accumulates quietly until a threshold is reached."""
    world = load(lay_out(tmp_path, MARKED))
    game = new_game(world)
    perform(world, game, "tap panel")
    assert game["marks"] == {"attention": 1}
    assert game["flags"] == {"tapped"}
    assert not game["over"]


def test_crossing_a_threshold_is_remembered(tmp_path):
    """The world remembers the crossing, and this world ends on that memory."""
    world = load(lay_out(tmp_path, MARKED))
    game = new_game(world)
    for _ in range(3):
        perform(world, game, "tap panel")
    assert game["marks"]["attention"] == 3
    assert "watched" in game["flags"]
    assert game["over"]


def test_two_moves_price_themselves_differently(tmp_path):
    """One action leaves more behind than another, and the count reflects it."""
    world = load(lay_out(tmp_path, MARKED))
    game = new_game(world)
    perform(world, game, "take token")
    perform(world, game, "redeem token")
    assert game["marks"]["attention"] == 2


def test_a_thing_spent_is_gone(tmp_path):
    """A thing an action spends is not carried afterwards: it was used up."""
    world = load(lay_out(tmp_path, MARKED))
    game = new_game(world)
    perform(world, game, "take token")
    assert "token" in game["inventory"]
    assert perform(world, game, "redeem token") == "Spent."
    assert "token" not in game["inventory"]
    assert perform(world, game, "redeem token") == said(world, "no_such_thing",
                                                        noun="token")


def test_a_world_with_no_marks_keeps_none(tmp_path):
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


def test_a_way_is_open_until_the_world_remembers_it_should_shut(tmp_path):
    """The mirror of requires: through is open now, and closed once noticed is set."""
    world = load(lay_out(tmp_path, SHUTS))
    game = new_game(world)
    assert perform(world, game, "through").startswith(world["rooms"]["plant"]["name"])
    perform(world, game, "back")
    perform(world, game, "tap panel")
    assert "noticed" in game["flags"]
    assert perform(world, game, "through") == said(world, "shut", dir="through")
    assert game["location"] == "office"


def test_a_shut_way_says_shut_not_blocked(tmp_path):
    """A way that closed is not a way that never opened; the words differ."""
    world = load(lay_out(tmp_path, SHUTS))
    game = new_game(world)
    perform(world, game, "tap panel")
    answer = perform(world, game, "through")
    assert answer == said(world, "shut", dir="through")
    assert answer != said(world, "blocked", dir="through")


def test_a_way_that_can_shut_is_warned_about(tmp_path):
    """The solver stays optimistic, so the validator names every way that can close."""
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


def test_a_hidden_way_is_unlisted_until_it_opens(tmp_path):
    """A hidden exit stays off the exits and help lists until it is genuinely passable."""
    world = load(lay_out(tmp_path, BOTH_GATES))
    game = new_game(world)
    world["rooms"]["fork"]["hidden"] = ["loud"]
    assert "loud" not in perform(world, game, "look")
    assert "loud" not in perform(world, game, "help")
    perform(world, game, "flip switch")
    assert "loud" in perform(world, game, "look")
    assert "loud" in perform(world, game, "help")


def test_one_memory_can_shut_one_way_and_open_another(tmp_path):
    """The defensive response: the same flag closes the quiet route and opens the loud one."""
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


def test_an_action_can_put_the_player_somewhere_else(tmp_path):
    """The costly move: firing the action leaves the player back where they started."""
    world = load(lay_out(tmp_path, THROWN))
    game = new_game(world)
    perform(world, game, "in")
    answer = perform(world, game, "probe console")
    assert game["location"] == "office"
    assert "noticed" in game["flags"]
    assert answer == "Escorted out.\n" + describe(world, game)


def test_an_action_that_stays_put_says_only_its_message(tmp_path):
    """Without goes, the reply is the message alone, as it always was."""
    world = load(lay_out(tmp_path, THROWN))
    game = new_game(world)
    del world["actions"]["probe"]["goes"]
    perform(world, game, "in")
    assert perform(world, game, "probe console") == "Escorted out."
    assert game["location"] == "server_room"


def test_describe_opens_the_game(tmp_path):
    """A client can describe the starting room without faking a turn."""
    world, game = started(tmp_path)
    assert describe(world, game).startswith("Cave mouth\n\n")
    assert game["moves"] == 0


def test_quit_ends_the_game(tmp_path):
    """The quit verb marks the game over rather than leaving clients to read the reply."""
    world, game = started(tmp_path)
    assert not game["over"]
    assert perform(world, game, "quit") == said(world, "goodbye")
    assert game["over"]


def test_save_and_restore_round_trip(tmp_path):
    """A saved game restores the location, inventory, flags and placements."""
    world, game = started(tmp_path)
    for command in ("take lamp", "light lamp", "in"):
        perform(world, game, command)
    assert perform(world, game, "save") == said(world, "saved")
    assert restore(tmp_path / "world" / "save.json", content_hash(game["source"]),
                   world["words"]["messages"]["player"]) == game


def test_restore_rejects_a_different_world(tmp_path):
    """A save made against other content is refused rather than half applied."""
    world, game = started(tmp_path)
    save(game, tmp_path / "world" / "save.json")
    (tmp_path / "world" / "world.toml").write_text("[meta]\ntitle = 'Other'\n")
    with pytest.raises(StateError) as refused:
        restore(tmp_path / "world" / "save.json", content_hash(game["source"]),
                world["words"]["messages"]["player"])
    assert str(refused.value) == said(world, "save_mismatch")


def test_restore_without_a_save_file(tmp_path):
    """Loading before saving reports that there is no saved game."""
    words = data.load(lay_out(tmp_path))["messages"]["player"]
    with pytest.raises(StateError) as refused:
        restore(tmp_path / "world" / "save.json", "any-hash", words)
    assert str(refused.value) == words["save_missing"]


@pytest.mark.parametrize("payload", [
    {}, {"game": []}, {"game": {"flags": 1}},
    {"game": {"location": "cave_mouth", "inventory": [], "flags": "abc", "fired": [],
              "moves": 0, "marks": {}, "placements": {}, "over": False}},
])
def test_restore_refuses_a_save_of_the_wrong_shape(payload, tmp_path):
    """A file that parses as JSON but is not a save is refused, not half applied."""
    world, game = started(tmp_path)
    path = tmp_path / "world" / "save.json"
    path.write_text(json.dumps(dict(payload, world_hash=content_hash(game["source"]))))
    with pytest.raises(StateError) as refused:
        restore(path, content_hash(game["source"]),
                world["words"]["messages"]["player"])
    assert str(refused.value) == said(world, "save_mismatch")


def test_a_builtin_verb_without_a_handler_is_unknown(tmp_path):
    """A world adding a verb the engine cannot run is told so, rather than crashing."""
    world = lay_out(tmp_path)
    (world / "builtins.toml").write_text("[verbs.shout]\nneeds_noun = false\n")
    loaded = load(world)
    game = new_game(loaded)
    assert perform(loaded, game, "shout") == said(loaded, "unknown_verb", word="shout")
    assert game["moves"] == 0


def test_every_built_in_verb_reaches_a_handler(tmp_path):
    """No verb or abbreviation in the data file is missing from the dispatch table."""
    world, game = started(tmp_path)
    builtins = world["words"]["builtins"]
    for verb in list(builtins["verbs"]) + list(builtins["abbreviations"]):
        assert perform(world, game, verb) != f"Unknown verb: {verb}."


def test_a_bare_verb_asks_for_what_is_missing(tmp_path):
    """A sentence the parser could not finish is not a puzzle refusing to open."""
    world, game = started(tmp_path)
    for verb in ("examine", "take", "drop", "dig"):
        assert perform(world, game, verb) == said(world, "needs_noun",
                                                  verb=verb.capitalize())
    assert perform(world, game, "go") == said(world, "needs_direction", verb="Go")


def test_a_way_stays_shut_until_what_it_asks_for_has_happened(tmp_path):
    """The flag gate refuses the exit during play, not only in the solver."""
    world, game = started(tmp_path)
    perform(world, game, "in")
    assert perform(world, game, "down") == said(world, "blocked", dir="down")
    for command in ("out", "take shovel", "in", "dig rubble"):
        perform(world, game, command)
    assert perform(world, game, "down").startswith(world["rooms"]["grotto"]["name"])


def test_a_thing_that_is_not_portable_stays_where_it_is(tmp_path):
    """Scenery answers with its own refusal and is still in the room afterwards."""
    world, game = started(tmp_path)
    for command in ("take lamp", "light lamp", "in"):
        perform(world, game, command)
    assert perform(world, game, "take rubble") == said(world, "not_portable")
    assert "rubble" in game["placements"]["debris_room"]
    assert "rubble" not in game["inventory"]


def test_an_action_fires_once_and_then_says_nothing_further(tmp_path):
    """A once action answers differently the second time, and sets no flag twice."""
    world, game = started(tmp_path)
    perform(world, game, "take lamp")
    assert perform(world, game, "light lamp") == \
        world["actions"]["light_lamp"]["message"]
    assert perform(world, game, "light lamp") == said(world, "already_done")
    assert game["flags"] == {"lamp_lit"}


def test_the_vague_answer_is_kept_for_the_puzzles(tmp_path):
    """The cases that could give a puzzle away still say nothing useful."""
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


def test_a_way_may_be_held_shut_until_a_thing_is_carried(tmp_path):
    """Holding asks what the player carries now, where requires asks what happened."""
    loaded = load(lay_out(tmp_path, HELD))
    game = new_game(loaded)
    assert perform(loaded, game, "north") == said(loaded, "blocked", dir="north")
    assert perform(loaded, game, "take ring") == said(loaded, "taken")
    assert perform(loaded, game, "north").startswith(loaded["rooms"]["vault"]["name"])
    perform(loaded, game, "south")
    perform(loaded, game, "drop ring")
    assert perform(loaded, game, "north") == said(loaded, "blocked", dir="north")


def test_the_solver_counts_a_held_way_as_openable(tmp_path):
    """A way held shut by a reachable thing is not an unreachable room."""
    assert "vault" in load(lay_out(tmp_path, HELD))["rooms"]


def test_a_multi_word_noun_is_joined_into_one_id(tmp_path):
    """A thing called Gold key has the id gold_key, and `take gold key` finds it."""
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


def test_an_unknown_noun_is_reported_in_the_words_the_player_used(tmp_path):
    """The underscores go back to spaces, so the answer quotes them, not the id."""
    world, game = started(tmp_path)
    assert perform(world, game, "take iron key") == said(
        world, "no_such_thing", noun="iron key")


def test_the_name_a_player_reads_is_a_name_they_can_type(tmp_path):
    """The room says brass lamp, so brass lamp works, whatever the id happens to be."""
    world, game = started(tmp_path)
    assert perform(world, game, "take brass lamp") == said(world, "taken")
    assert "lamp" in game["inventory"]


def test_one_word_is_enough_when_only_one_thing_fits(tmp_path):
    """A bare word finds the thing it names, the way the old games did."""
    loaded = load(lay_out(tmp_path, HELD))
    game = new_game(loaded)
    assert perform(loaded, game, "take ring") == said(loaded, "taken")
    assert "ring" in game["inventory"]


def test_words_that_fit_two_things_are_asked_about(tmp_path):
    """Where the words fit more than one thing here, the game asks rather than guesses."""
    world = load(lay_out(tmp_path, TWO_BRASS))
    game = new_game(world)
    answer = perform(world, game, "take brass")
    assert answer == said(world, "which_one", things="brass lamp, brass bell")
    assert game["inventory"] == []


def test_a_direction_is_never_resolved_as_a_thing(tmp_path):
    """go north is a way out, not an attempt to find something called north."""
    world, game = started(tmp_path)
    for command in ("take lamp", "light lamp"):
        perform(world, game, command)
    assert perform(world, game, "go in").startswith(
        world["rooms"]["debris_room"]["name"])


def test_help_answers_for_where_the_player_stands(tmp_path):
    """It lists the ways out and the things here, not the game in general."""
    world, game = started(tmp_path)
    assert perform(world, game, "help") == (
        "Ways out: in.\n"
        "take: lamp, shovel.\n"
        "examine: lamp, shovel.\n"
        "light: lamp.\n"
        "Always: look, inventory, save, load, quit, help.\n"
        "Short forms: l for look, i for inventory.")


def test_help_follows_what_the_player_is_carrying(tmp_path):
    """Taking something moves it from what can be taken to what can be dropped."""
    world, game = started(tmp_path)
    perform(world, game, "take lamp")
    said = perform(world, game, "help")
    assert "take: shovel." in said
    assert "drop: lamp." in said


def test_help_offers_this_world_s_own_verbs(tmp_path):
    """A verb the world adds is offered where its thing is, and nowhere else."""
    world, game = started(tmp_path)
    perform(world, game, "take lamp")
    assert "light: lamp." in perform(world, game, "help")
    perform(world, game, "drop lamp")
    perform(world, game, "in")
    assert "light" not in perform(world, game, "help")


def test_help_withholds_what_the_dark_forbids(tmp_path):
    """A dark room offers no take and no examine, but still offers the way out."""
    world, game = started(tmp_path)
    perform(world, game, "in")
    said = perform(world, game, "help")
    assert said.startswith("Ways out: out, down.")
    assert "take:" not in said
    assert "examine:" not in said


def test_load_verb_reports_a_missing_save(tmp_path):
    """The load verb returns the message rather than raising at the player."""
    world, game = started(tmp_path)
    assert perform(world, game, "load") == said(world, "save_missing")


def test_a_world_that_says_nothing_is_refused(tmp_path):
    """There is no shared voice to fall back on, so a silent world does not load."""
    world = lay_out(tmp_path)
    (world / "messages.toml").unlink()
    with pytest.raises(WorldError) as refused:
        load(world)
    assert "world says nothing for:" in str(refused.value)


def test_a_world_missing_one_line_is_refused_by_that_line(tmp_path):
    """The refusal names what is unsaid, so the author knows what to write."""
    world = lay_out(tmp_path)
    said_lines = (world / "messages.toml").read_text()
    (world / "messages.toml").write_text(
        said_lines.replace('goodbye = "Goodbye."\n', ""))
    with pytest.raises(WorldError) as refused:
        load(world)
    assert "goodbye" in str(refused.value)


def test_two_worlds_differ_in_one_process():
    """Each world says every line for itself, and neither world leaks into the other."""
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
