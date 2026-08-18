"""The solver's waves and reachability for the sample world."""

from engine.world import load, reachable_from, solvable
from tests.conftest import lay_out

# wave 1 opens cave_mouth and debris_room with both flags, wave 2 the grotto.
EXPECTED_WAVES = [
    {"rooms": ["cave_mouth", "debris_room"], "flags": ["lamp_lit", "rubble_cleared"]},
    {"rooms": ["grotto"], "flags": []},
]


def test_waves(world):
    """The sample world opens in the two waves, in file order."""
    _rooms, _flags, waves = solvable(load(world))
    assert waves == EXPECTED_WAVES


def test_fixed_point(world):
    """Every room and both flags are reached."""
    rooms, flags, _waves = solvable(load(world))
    assert rooms == {"cave_mouth", "debris_room", "grotto"}
    assert flags == {"lamp_lit", "rubble_cleared"}


def test_gated_room_needs_its_flag(world):
    """Without the action that clears the rubble, the grotto never opens."""
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


def test_a_wave_lists_its_flags_in_file_order(tmp_path):
    """File order, not alphabetical: the sample world cannot tell the two apart."""
    _rooms, _flags, waves = solvable(load(lay_out(tmp_path, ORDERED)))
    assert waves[0]["flags"] == ["zeta", "alpha"]


def test_reachable_ignores_gates(world):
    """Breadth-first reachability crosses the gated exit the solver has to earn."""
    world = load(world)
    assert reachable_from(world, "cave_mouth") == {"cave_mouth", "debris_room", "grotto"}
    assert reachable_from(world, "grotto") == {"grotto", "debris_room", "cave_mouth"}
    assert reachable_from(world, "nowhere") == set()
