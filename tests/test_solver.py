from engine.world import load, reachable_from, solvable
from tests.conftest import lay_out

# wave 1 opens cave_mouth and debris_room with both flags, wave 2 the grotto.
EXPECTED_WAVES = [
    {"rooms": ["cave_mouth", "debris_room"], "flags": ["lamp_lit", "rubble_cleared"]},
    {"rooms": ["grotto"], "flags": []}
]


def test_waves(world):
    _rooms, _flags, waves = solvable(load(world))
    assert waves == EXPECTED_WAVES


def test_fixed_point(world):
    rooms, flags, _waves = solvable(load(world))
    assert rooms == {"cave_mouth", "debris_room", "grotto"}
    assert flags == {"lamp_lit", "rubble_cleared"}


def test_gate(world):
    loaded = load(world)
    ungated = dict(loaded, actions={"light_lamp": loaded["actions"]["light_lamp"]})
    rooms, _flags, waves = solvable(ungated)
    assert rooms == {"cave_mouth", "debris_room"}
    assert waves == [{"rooms": ["cave_mouth", "debris_room"], "flags": ["lamp_lit"]}]


ORDERED = ('[meta]\ntitle = "O"\nstart = "hall"\nversion = 1\n\n'
           '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\n'
           'oneway = true\nthings = ["bell", "horn"]\n\n'
           '[things.bell]\nname = "Bell"\n\n[things.horn]\nname = "Horn"\n\n'
           '[actions.ring_bell]\nverb = "ring"\nnoun = "bell"\n'
           'sets = ["zeta"]\nmessage = "It rings."\n\n'
           '[actions.blow_horn]\nverb = "blow"\nnoun = "horn"\n'
           'sets = ["alpha"]\nmessage = "It sounds."\n')


def test_wave_order(tmp_path):
    _rooms, _flags, waves = solvable(load(lay_out(tmp_path, ORDERED)))
    assert waves[0]["flags"] == ["zeta", "alpha"]


DROPPED = ('[meta]\ntitle = "C"\nstart = "hall"\nversion = 1\n\n'
           '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\n'
           'oneway = true\nthings = ["rope"]\n\n'
           '[rooms.cell]\nname = "Cell"\ndesc = "A cell."\noneway = true\n\n'
           '[things.rope]\nname = "rope"\n\n'
           '[actions.pull_rope]\nverb = "pull"\nnoun = "rope"\n'
           'goes = "cell"\nsets = ["fell"]\nmessage = "Down you go."\n')


def test_goes(tmp_path):
    """No exit reaches the cell; the action that sends the player there is enough."""
    world = load(lay_out(tmp_path, DROPPED))
    rooms, _flags, _waves = solvable(world)
    assert "cell" in rooms
    assert reachable_from(world, "hall") == {"hall", "cell"}


def test_reachable(world):
    """Breadth-first reachability crosses the gated exit the solver has to earn."""
    world = load(world)
    assert reachable_from(world, "cave_mouth") == {"cave_mouth", "debris_room", "grotto"}
    assert reachable_from(world, "grotto") == {"grotto", "debris_room", "cave_mouth"}
    assert reachable_from(world, "nowhere") == set()
