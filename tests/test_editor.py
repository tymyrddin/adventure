"""The editor reports the file on disk as it stands, and writes it back atomically."""

import tomllib

import pytest

from editor import writer
from editor.app import create_app
from tests.conftest import SAMPLE, WORLDS, broken, lay_out


@pytest.fixture
def client(world):
    """Return a test client for a copy of the sample world."""
    return _client(world)


def _client(where):
    """Return a test client for the world in this directory."""
    app = create_app(where)
    app.config["TESTING"] = True
    return app.test_client()


def test_index_renders_the_page_the_map_is_drawn_on(client):
    """The shell carries the title and the containers the JS fills."""
    with open(SAMPLE, "rb") as handle:
        title = tomllib.load(handle)["meta"]["title"]
    page = client.get("/").get_data(as_text=True)
    assert title in page
    for anchor in ('id="graph"', 'id="panel"', 'id="report"',
                   "cytoscape.min.js", "graph.js"):
        assert anchor in page


def test_world_route_returns_the_file_and_its_mtime(client):
    """The whole file comes back as JSON, in file order, with a modification time."""
    body = client.get("/api/world").get_json()
    assert list(body["world"]["rooms"]) == ["cave_mouth", "debris_room", "grotto"]
    assert body["world"]["meta"]["start"] == "cave_mouth"
    assert isinstance(body["mtime"], float)


def test_validate_route_reports_a_clean_world(client):
    """The sample world validates with no errors, no warnings and two waves."""
    body = client.post("/api/validate").get_json()
    assert body["errors"] == []
    assert body["warnings"] == []
    assert body["waves"] == [
        {"rooms": ["cave_mouth", "debris_room"], "flags": ["lamp_lit", "rubble_cleared"]},
        {"rooms": ["grotto"], "flags": []},
    ]


def test_validate_route_reports_a_broken_world(tmp_path):
    """A file the engine would refuse is reported rather than hidden."""
    body = _client(broken(tmp_path, "exit_unknown_room.toml")).post("/api/validate").get_json()
    assert "hall: exit north leads to unknown room nowhere" in body["errors"]


def test_graph_route_describes_the_map(client):
    """Nodes carry reachability, wave and darkness; edges carry gate and hiding."""
    graph = client.get("/api/graph").get_json()
    assert graph["nodes"] == [
        {"id": "cave_mouth", "name": "Cave mouth", "reachable": True, "wave": 1,
         "dark": False, "start": True, "x": 0, "y": 0, "placed": False},
        {"id": "debris_room", "name": "Debris room", "reachable": True, "wave": 1,
         "dark": True, "start": False, "x": 220, "y": 0, "placed": False},
        {"id": "grotto", "name": "Grotto", "reachable": True, "wave": 2,
         "dark": False, "start": False, "x": 440, "y": 0, "placed": False},
    ]
    assert graph["edges"] == [
        {"from": "cave_mouth", "to": "debris_room", "dir": "in", "gate": None,
         "holds": None, "hidden": False, "shuts": None,
         "pair": "cave_mouth|debris_room|in|out"},
        {"from": "debris_room", "to": "cave_mouth", "dir": "out", "gate": None,
         "holds": None, "hidden": False, "shuts": None,
         "pair": "cave_mouth|debris_room|in|out"},
        {"from": "debris_room", "to": "grotto", "dir": "down",
         "gate": "rubble_cleared", "holds": None, "hidden": False,
         "shuts": None, "pair": None},
        {"from": "grotto", "to": "debris_room", "dir": "up", "gate": None,
         "holds": None, "hidden": False, "shuts": None, "pair": None},
    ]


def test_a_hidden_exit_is_not_paired_with_its_reverse(client):
    """Hiding one half is a difference the map has to keep showing."""
    _send(client, "put", "/api/rooms/grotto",
          room={"name": "Grotto", "desc": "A grotto.",
                "exits": {"up": "debris_room"}, "hidden": ["up"]})
    assert [edge["pair"] for edge in client.get("/api/graph").get_json()["edges"]
            if edge["from"] == "grotto"] == [None]


def test_graph_marks_a_room_no_gate_ever_opens(tmp_path):
    """A room the solver never reaches carries a null wave, though the map connects."""
    graph = _client(broken(tmp_path, "requires_unknown_flag.toml")).get(
        "/api/graph").get_json()
    cellar = next(node for node in graph["nodes"] if node["id"] == "cellar")
    assert cellar["reachable"] is True
    assert cellar["wave"] is None


def test_unparsable_file_refuses_the_data_routes(tmp_path):
    """The world and graph routes answer 422, and validation still reports."""
    client = _client(broken(tmp_path, "malformed.toml"))
    assert client.get("/api/world").status_code == 422
    assert client.get("/api/graph").status_code == 422
    assert client.post("/api/validate").get_json()["errors"] != []
    assert "will not parse" in client.get("/").get_data(as_text=True)


def test_a_world_file_that_has_gone_is_reported_not_raised(client, tmp_path):
    """Every route answers in words when the file it was opened on disappears."""
    mtime = client.get("/api/world").get_json()["mtime"]
    (tmp_path / "world" / "world.toml").unlink()
    assert client.get("/").status_code == 200
    assert client.get("/api/world").status_code == 422
    assert client.get("/api/graph").status_code == 422
    assert client.post("/api/validate").get_json()["errors"] != []
    written = client.put("/api/meta", json={"mtime": mtime, "meta": {"title": "T"}})
    assert written.status_code == 422


def test_routes_read_the_file_each_time(client, tmp_path):
    """An edit made on disk shows up without restarting the editor."""
    assert client.post("/api/validate").get_json()["errors"] == []
    (tmp_path / "world" / "world.toml").write_text(
        (WORLDS / "start_missing.toml").read_text())
    assert client.post("/api/validate").get_json()["errors"] == [
        "start room void does not exist"]


def _send(client, method, url, **body):
    """Send one write carrying the modification time the client would have loaded."""
    mtime = client.get("/api/world").get_json()["mtime"]
    return getattr(client, method)(url, json=dict(body, mtime=mtime))


def _world(tmp_path):
    """Return the world file as plain data."""
    with open(tmp_path / "world" / "world.toml", "rb") as handle:
        return tomllib.load(handle)


def test_place_lays_out_a_world_that_carries_no_coordinates():
    """Every room of the sample world falls on the grid."""
    with open(SAMPLE, "rb") as handle:
        assert writer.place(tomllib.load(handle)) == {
            "cave_mouth": {"x": 0, "y": 0, "placed": False},
            "debris_room": {"x": 220, "y": 0, "placed": False},
            "grotto": {"x": 440, "y": 0, "placed": False},
        }


def test_place_puts_the_loose_rooms_below_the_placed_ones():
    """A room with both coordinates keeps them; the grid starts one row under it."""
    world = {"rooms": {"hall": {"x": 40, "y": 90}, "attic": {}, "cellar": {}}}
    assert writer.place(world) == {
        "hall": {"x": 40, "y": 90, "placed": True},
        "attic": {"x": 0, "y": 310, "placed": False},
        "cellar": {"x": 220, "y": 310, "placed": False},
    }


def test_place_ignores_a_room_holding_only_one_coordinate():
    """Half a position is no position, so the room goes on the grid."""
    assert writer.place({"rooms": {"hall": {"x": 40}}}) == {
        "hall": {"x": 0, "y": 0, "placed": False}}


def test_creating_a_room_connects_it_both_ways(client, tmp_path):
    """The source gains the exit asked for, and the new room gains its opposite."""
    response = _send(client, "post", "/api/rooms",
                     room={"name": "Tunnel", "desc": "A tunnel."},
                     **{"from": {"room": "grotto", "dir": "north"}})
    assert response.status_code == 200
    rooms = _world(tmp_path)["rooms"]
    assert rooms["grotto"]["exits"]["north"] == "tunnel"
    assert rooms["tunnel"]["exits"]["south"] == "grotto"


def test_a_new_passage_can_be_locked_as_it_is_made(client, tmp_path):
    """The condition belongs where the passage is made, not in a later visit."""
    assert _send(client, "post", "/api/rooms",
                 room={"name": "Vault", "desc": "A vault."},
                 **{"from": {"room": "grotto", "dir": "north",
                             "gate": "rubble_cleared"}}).status_code == 200
    grotto = _world(tmp_path)["rooms"]["grotto"]
    assert grotto["exits"]["north"] == "vault"
    assert grotto["requires"]["north"] == "rubble_cleared"


def test_the_way_back_is_not_locked_with_it(client, tmp_path):
    """A player who got in can always get out again."""
    _send(client, "post", "/api/rooms",
          room={"name": "Vault", "desc": "A vault."},
          **{"from": {"room": "grotto", "dir": "north", "gate": "rubble_cleared"}})
    assert "requires" not in _world(tmp_path)["rooms"]["vault"]


def test_a_new_room_is_placed_in_the_direction_it_was_made(client, tmp_path):
    """North of the grotto means one spacing above it, so the map lays itself out."""
    _send(client, "post", "/api/rooms",
          room={"name": "Tunnel", "desc": "A tunnel."},
          **{"from": {"room": "grotto", "dir": "north"}})
    tunnel = _world(tmp_path)["rooms"]["tunnel"]
    assert (tunnel["x"], tunnel["y"]) == (440, -220)


def test_a_new_room_in_an_invented_direction_goes_below(client, tmp_path):
    """A direction with no compass meaning still has somewhere to be drawn."""
    _send(client, "post", "/api/rooms",
          room={"name": "Burrow", "desc": "A burrow."},
          **{"from": {"room": "grotto", "dir": "crawl"}})
    burrow = _world(tmp_path)["rooms"]["burrow"]
    assert (burrow["x"], burrow["y"]) == (440, 220)


def test_a_new_room_keeps_the_coordinates_it_was_given(client, tmp_path):
    """A body that carries a position is not second-guessed."""
    _send(client, "post", "/api/rooms",
          room={"name": "Tunnel", "desc": "A tunnel.", "x": 7, "y": 9},
          **{"from": {"room": "grotto", "dir": "north"}})
    tunnel = _world(tmp_path)["rooms"]["tunnel"]
    assert (tunnel["x"], tunnel["y"]) == (7, 9)


def test_creating_a_room_expands_a_direction_abbreviation(client, tmp_path):
    """`n` is written as `north`, so the file never carries an abbreviation."""
    _send(client, "post", "/api/rooms",
          room={"name": "Tunnel", "desc": "A tunnel."},
          **{"from": {"room": "grotto", "dir": "n"}})
    rooms = _world(tmp_path)["rooms"]
    assert list(rooms["grotto"]["exits"]) == ["up", "north"]
    assert rooms["tunnel"]["exits"] == {"south": "grotto"}


def test_creating_a_room_can_refuse_the_reverse_exit(client, tmp_path):
    """With reverse off, the passage runs one way and the new room has no exits."""
    _send(client, "post", "/api/rooms",
          room={"name": "Pit", "desc": "A pit.", "oneway": True},
          **{"from": {"room": "grotto", "dir": "down", "reverse": False}})
    assert "exits" not in _world(tmp_path)["rooms"]["pit"]


def test_a_direction_with_no_opposite_leaves_the_new_room_exitless(client, tmp_path):
    """An invented direction gets no reverse, and the warning says so."""
    response = _send(client, "post", "/api/rooms",
                     room={"name": "Burrow", "desc": "A burrow."},
                     **{"from": {"room": "grotto", "dir": "crawl"}})
    assert response.status_code == 200
    assert _world(tmp_path)["rooms"]["grotto"]["exits"]["crawl"] == "burrow"
    assert "exits" not in _world(tmp_path)["rooms"]["burrow"]
    assert "burrow: no exits and not marked oneway" in (
        client.post("/api/validate").get_json()["warnings"])


def test_creating_a_room_with_no_connection_is_refused(client, tmp_path):
    """A room joined to nothing is unreachable, and the gate says so."""
    before = (tmp_path / "world" / "world.toml").read_bytes()
    response = _send(client, "post", "/api/rooms",
                     room={"name": "Attic", "desc": "An attic.", "oneway": True})
    assert response.status_code == 422
    assert response.get_json()["errors"] == ["unreachable rooms: attic"]
    assert (tmp_path / "world" / "world.toml").read_bytes() == before


def test_a_name_already_in_use_steps_past_it(client, tmp_path):
    """The id a name spells is taken, so the next free one is used instead."""
    response = _send(client, "post", "/api/rooms",
                     room={"name": "Grotto", "desc": "Another grotto."},
                     **{"from": {"room": "grotto", "dir": "north"}})
    assert response.status_code == 200
    assert response.get_json()["id"] == "grotto_2"
    assert _world(tmp_path)["rooms"]["grotto_2"]["name"] == "Grotto"


def test_replacing_a_room_keeps_the_coordinates_the_body_omits(client, tmp_path):
    """A panel that does not show x and y must not throw them away."""
    _send(client, "put", "/api/layout", positions={"grotto": {"x": 40, "y": 90}})
    _send(client, "put", "/api/rooms/grotto",
          room={"name": "Grotto", "desc": "Changed.", "exits": {"up": "debris_room"}})
    grotto = _world(tmp_path)["rooms"]["grotto"]
    assert grotto["desc"] == "Changed."
    assert (grotto["x"], grotto["y"]) == (40, 90)


def test_renaming_a_room_moves_its_id_and_what_points_at_it(client, tmp_path):
    """The name is the identity, so renaming rewrites the key and every reference."""
    assert _send(client, "put", "/api/rooms/grotto",
                 room={"name": "Glitter hall", "desc": "A grotto.",
                       "exits": {"up": "debris_room"}}).status_code == 200
    world = _world(tmp_path)
    assert "grotto" not in world["rooms"]
    assert world["rooms"]["glitter_hall"]["name"] == "Glitter hall"
    assert world["rooms"]["debris_room"]["exits"]["down"] == "glitter_hall"
    assert list(world["rooms"]) == ["cave_mouth", "debris_room", "glitter_hall"]


def test_renaming_the_start_room_follows_into_meta(client, tmp_path):
    """Nothing may be left pointing at a name that has gone."""
    _send(client, "put", "/api/rooms/cave_mouth",
          room={"name": "Cave entrance", "desc": "At the mouth.",
                "exits": {"in": "debris_room"}, "things": ["lamp", "shovel"]})
    assert _world(tmp_path)["meta"]["start"] == "cave_entrance"


def test_renaming_a_thing_follows_into_rooms_and_actions(client, tmp_path):
    """A thing's placement and the actions that use it are rewritten with it."""
    assert _send(client, "put", "/api/things/shovel",
                 thing={"name": "iron spade", "portable": True}).status_code == 200
    world = _world(tmp_path)
    assert "shovel" not in world["things"]
    assert world["rooms"]["cave_mouth"]["things"] == ["lamp", "iron_spade"]
    assert world["actions"]["dig_rubble"]["needs"] == ["iron_spade"]


def test_a_rename_onto_a_taken_id_is_refused(client, tmp_path):
    """Two records cannot share one identity, so the write is refused whole."""
    before = (tmp_path / "world" / "world.toml").read_bytes()
    response = _send(client, "put", "/api/rooms/grotto",
                     room={"name": "Debris room", "desc": "A grotto.",
                           "exits": {"up": "debris_room"}})
    assert response.status_code == 409
    assert response.get_json()["errors"] == [
        "There is already a room called debris_room."]
    assert (tmp_path / "world" / "world.toml").read_bytes() == before


def test_replacing_an_absent_room_is_refused(client):
    """A 404 names the id that is not there."""
    response = _send(client, "put", "/api/rooms/nowhere",
                     room={"name": "Nowhere", "desc": "Nowhere."})
    assert response.status_code == 404
    assert response.get_json()["errors"] == ["There is no room called nowhere."]


def test_deleting_a_room_takes_the_exits_that_led_to_it(client, tmp_path):
    """A neighbour loses the exit, its gate and its hiding, so the file stays valid."""
    _send(client, "put", "/api/rooms/debris_room",
          room={"name": "Debris room", "desc": "A room full of debris.", "dark": True,
                "exits": {"out": "cave_mouth", "down": "grotto"},
                "requires": {"down": "rubble_cleared"}, "hidden": ["down"],
                "things": ["rubble"]})
    assert _send(client, "delete", "/api/rooms/grotto").status_code == 200
    world = _world(tmp_path)
    assert "grotto" not in world["rooms"]
    assert world["rooms"]["debris_room"]["exits"] == {"out": "cave_mouth"}
    assert world["rooms"]["debris_room"]["requires"] == {}
    assert world["rooms"]["debris_room"]["hidden"] == []


def test_deleting_a_room_an_action_happens_in_is_refused(tmp_path):
    """An action's in_room holds the room in place as firmly as an exit does."""
    world = lay_out(tmp_path, '[meta]\ntitle = "A"\nstart = "hall"\nversion = 1\n\n'
                     '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\noneway = true\n\n'
                     '[rooms.attic]\nname = "Attic"\ndesc = "An attic."\noneway = true\n\n'
                     '[things.box]\nname = "box"\n\n'
                     '[actions.open_box]\nverb = "open"\nnoun = "box"\n'
                     'in_room = "attic"\nsets = ["opened"]\nmessage = "Open."\n')
    response = _send(_client(world), "delete", "/api/rooms/attic")
    assert response.status_code == 409
    assert response.get_json()["errors"] == [
        "attic: action open_box happens there."]


def test_a_room_can_be_made_and_then_deleted_again(client, tmp_path):
    """Creating a room and removing it returns the world to what it was."""
    before = _world(tmp_path)
    _send(client, "post", "/api/rooms",
          room={"name": "Tunnel", "desc": "A tunnel."},
          **{"from": {"room": "grotto", "dir": "north"}})
    assert _send(client, "delete", "/api/rooms/tunnel").status_code == 200
    assert _world(tmp_path) == before


def test_deleting_a_thing_an_action_uses_is_refused(client):
    """A thing an action names as its noun or in needs stays put."""
    response = _send(client, "delete", "/api/things/lamp")
    assert response.status_code == 409
    assert response.get_json()["errors"] == ["lamp: action light_lamp uses it."]


def test_deleting_a_thing_takes_its_placement_with_it(client, tmp_path):
    """The room that held the thing loses it, so the file stays valid."""
    assert _send(client, "post", "/api/things",
                 thing={"name": "a coin"}).get_json()["id"] == "a_coin"
    _send(client, "put", "/api/rooms/grotto",
          room={"name": "Grotto", "desc": "A grotto.",
                "exits": {"up": "debris_room"}, "things": ["a_coin"]})
    assert _world(tmp_path)["rooms"]["grotto"]["things"] == ["a_coin"]
    assert _send(client, "delete", "/api/things/a_coin").status_code == 200
    assert _world(tmp_path)["rooms"]["grotto"]["things"] == []
    assert "a_coin" not in _world(tmp_path)["things"]


def test_actions_are_created_replaced_and_deleted(client, tmp_path):
    """The action table takes the same three routes as the others."""
    assert _send(client, "post", "/api/actions",
                 action={"verb": "rub", "noun": "lamp", "needs": ["lamp"],
                         "sets": ["rubbed"], "message": "You rub it."}
                 ).status_code == 200
    _send(client, "put", "/api/actions/rub_lamp",
          action={"verb": "rub", "noun": "lamp", "needs": ["lamp"],
                  "sets": ["rubbed"], "message": "Nothing happens."})
    assert _world(tmp_path)["actions"]["rub_lamp"]["message"] == "Nothing happens."
    assert _send(client, "delete", "/api/actions/rub_lamp").status_code == 200
    assert "rub_lamp" not in _world(tmp_path)["actions"]


def test_meta_takes_an_ending_and_can_clear_it(client, tmp_path):
    """The world panel can set the game's ending flag, and remove it again."""
    _send(client, "put", "/api/meta", meta={"title": "U", "start": "cave_mouth",
                                            "ending": "rubble_cleared"})
    assert _world(tmp_path)["meta"]["ending"] == "rubble_cleared"
    _send(client, "put", "/api/meta", meta={"title": "U", "start": "cave_mouth",
                                            "ending": ""})
    assert "ending" not in _world(tmp_path)["meta"]


def test_meta_takes_a_title_and_a_start_room_but_not_a_version(client, tmp_path):
    """The version is the engine's business and the route leaves it alone."""
    assert _send(client, "put", "/api/meta",
                 meta={"title": "Over the Hill", "start": "grotto", "version": 2}
                 ).status_code == 200
    meta = _world(tmp_path)["meta"]
    assert (meta["title"], meta["start"], meta["version"]) == (
        "Over the Hill", "grotto", 1)


def test_marks_are_written_and_cleared_as_a_table(client, tmp_path):
    """The world panel replaces the whole marks table, and can empty it again."""
    _send(client, "put", "/api/marks",
          marks={"attention": {"threshold": 2, "sets": "watched"}})
    assert _world(tmp_path)["marks"]["attention"] == {"threshold": 2, "sets": "watched"}
    _send(client, "put", "/api/marks", marks={})
    assert "marks" not in _world(tmp_path)


def test_a_mark_with_a_zero_threshold_is_refused(client, tmp_path):
    """The validator's floor holds through the editor: a threshold must be positive."""
    before = (tmp_path / "world" / "world.toml").read_bytes()
    response = _send(client, "put", "/api/marks",
                     marks={"attention": {"threshold": 0, "sets": "watched"}})
    assert response.status_code == 422
    assert (tmp_path / "world" / "world.toml").read_bytes() == before


def test_layout_writes_rounded_coordinates(client, tmp_path):
    """Dragged positions arrive as floats and land in the file as integers."""
    assert _send(client, "put", "/api/layout",
                 positions={"grotto": {"x": 12.6, "y": -3.2}}).status_code == 200
    grotto = _world(tmp_path)["rooms"]["grotto"]
    assert (grotto["x"], grotto["y"]) == (13, -3)


def test_layout_moves_the_grid_below_what_it_placed(client):
    """A single placed room pushes every unplaced one a row underneath it."""
    _send(client, "put", "/api/layout", positions={"grotto": {"x": 12.6, "y": -3.2}})
    spots = {node["id"]: (node["x"], node["y"], node["placed"])
             for node in client.get("/api/graph").get_json()["nodes"]}
    assert spots == {"cave_mouth": (0, 217, False), "debris_room": (220, 217, False),
                     "grotto": (13, -3, True)}


def test_layout_refuses_a_room_that_is_not_there(client):
    """Positions are only written for rooms the file knows."""
    response = _send(client, "put", "/api/layout", positions={"nowhere": {"x": 1, "y": 2}})
    assert response.status_code == 404


def test_a_write_that_would_break_the_world_changes_nothing(client, tmp_path):
    """The gate answers with the validator's own lines and leaves the file alone."""
    before = (tmp_path / "world" / "world.toml").read_bytes()
    response = _send(client, "put", "/api/rooms/grotto",
                     room={"name": "Grotto", "desc": "A grotto.",
                           "exits": {"up": "debris_room", "north": "nowhere"}})
    assert response.status_code == 422
    assert response.get_json()["errors"] == [
        "grotto: exit north leads to unknown room nowhere"]
    assert (tmp_path / "world" / "world.toml").read_bytes() == before


def test_a_stale_mtime_refuses_the_write(client, tmp_path):
    """The file changed under the author, so the write is refused whole."""
    before = (tmp_path / "world" / "world.toml").read_bytes()
    response = client.put("/api/rooms/grotto", json={
        "mtime": 0.0, "room": {"name": "Grotto", "desc": "Changed."}})
    assert response.status_code == 409
    assert response.get_json()["errors"] == ["File changed on disk since load."]
    assert (tmp_path / "world" / "world.toml").read_bytes() == before


@pytest.mark.parametrize("method,url", [
    ("post", "/api/rooms"), ("put", "/api/rooms/grotto"),
    ("delete", "/api/rooms/grotto"), ("put", "/api/things/lamp"),
    ("put", "/api/meta"), ("put", "/api/layout")])
def test_a_write_without_an_mtime_is_refused(method, url, client):
    """Every write route asks what the client had loaded."""
    response = getattr(client, method)(url, json={
        "id": "attic", "room": {"name": "Attic", "desc": "An attic."}})
    assert response.status_code == 400
    assert response.get_json()["errors"] == [
        "The request body is not the shape this route takes."]


def test_writing_keeps_the_comments_and_the_key_order(tmp_path):
    """tomlkit round-trips the file, so an author's own file survives an edit."""
    world = lay_out(tmp_path, '# The world above the hill.\n[meta]\ntitle = "A"\n'
                     'start = "hall"\nversion = 1\n\n'
                     '# The only room.\n[rooms.hall]\nname = "Hall"\n'
                     'desc = "A hall."\noneway = true\n')
    _send(_client(world), "put", "/api/layout", positions={"hall": {"x": 1, "y": 2}})
    written = (world / "world.toml").read_text()
    assert "# The world above the hill." in written
    assert "# The only room." in written
    assert written.index("name") < written.index("desc") < written.index("x = 1")
