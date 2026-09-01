import tomllib

import pytest

from editor import writer
from editor.app import create_app
from tests.conftest import SAMPLE, WORLDS, broken, lay_out


@pytest.fixture
def client(world):
    return _client(world)


def _client(where):
    app = create_app(where)
    app.config["TESTING"] = True
    return app.test_client()


def test_index(client):
    """The shell carries the title and the containers the JS fills."""
    with open(SAMPLE, "rb") as handle:
        title = tomllib.load(handle)["meta"]["title"]
    page = client.get("/").get_data(as_text=True)
    assert title in page
    for anchor in ('id="graph"', 'id="panel"', 'id="report"',
                   "cytoscape.min.js", "graph.js"):
        assert anchor in page


def test_world_route(client):
    """The whole file comes back as JSON, in file order, with a modification time."""
    body = client.get("/api/world").get_json()
    assert list(body["world"]["rooms"]) == ["cave_mouth", "debris_room", "grotto"]
    assert body["world"]["meta"]["start"] == "cave_mouth"
    assert isinstance(body["mtime"], float)


def test_validate_clean(client):
    """The sample world validates with no errors, no warnings and two waves."""
    body = client.post("/api/validate").get_json()
    assert body["errors"] == []
    assert body["warnings"] == []
    assert body["waves"] == [
        {"rooms": ["cave_mouth", "debris_room"], "flags": ["lamp_lit", "rubble_cleared"]},
        {"rooms": ["grotto"], "flags": []}
    ]


def test_validate_broken(tmp_path):
    """A file the engine would refuse is reported rather than hidden."""
    body = _client(broken(tmp_path, "exit_unknown_room.toml")).post("/api/validate").get_json()
    assert "hall: exit north leads to unknown room nowhere" in body["errors"]


def test_graph(client):
    graph = client.get("/api/graph").get_json()
    assert graph["nodes"] == [
        {"id": "cave_mouth", "name": "Cave mouth", "reachable": True, "wave": 1,
         "dark": False, "start": True, "x": 0, "y": 0, "placed": False},
        {"id": "debris_room", "name": "Debris room", "reachable": True, "wave": 1,
         "dark": True, "start": False, "x": 220, "y": 0, "placed": False},
        {"id": "grotto", "name": "Grotto", "reachable": True, "wave": 2,
         "dark": False, "start": False, "x": 440, "y": 0, "placed": False}
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
         "holds": None, "hidden": False, "shuts": None, "pair": None}
    ]
    assert graph["goes"] == []


def test_hidden_unpaired(client):
    _send(client, "put", "/api/rooms/grotto",
          room={"name": "Grotto", "desc": "A grotto.",
                "exits": {"up": "debris_room"}, "hidden": ["up"]})
    assert [edge["pair"] for edge in client.get("/api/graph").get_json()["edges"]
            if edge["from"] == "grotto"] == [None]


def test_graph_null_wave(tmp_path):
    graph = _client(broken(tmp_path, "requires_unknown_flag.toml")).get(
        "/api/graph").get_json()
    cellar = next(node for node in graph["nodes"] if node["id"] == "cellar")
    assert cellar["reachable"] is True
    assert cellar["wave"] is None


def test_unparsable(tmp_path):
    client = _client(broken(tmp_path, "malformed.toml"))
    assert client.get("/api/world").status_code == 422
    assert client.get("/api/graph").status_code == 422
    assert client.post("/api/validate").get_json()["errors"] != []
    assert "will not parse" in client.get("/").get_data(as_text=True)


def test_file_gone(client, tmp_path):
    """Every route answers in words when the file it was opened on disappears."""
    mtime = client.get("/api/world").get_json()["mtime"]
    (tmp_path / "world" / "world.toml").unlink()
    assert client.get("/").status_code == 200
    assert client.get("/api/world").status_code == 422
    assert client.get("/api/graph").status_code == 422
    assert client.post("/api/validate").get_json()["errors"] != []
    written = client.put("/api/meta", json={"mtime": mtime, "meta": {"title": "T"}})
    assert written.status_code == 422


def test_reread(client, tmp_path):
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


def test_place():
    with open(SAMPLE, "rb") as handle:
        assert writer.place(tomllib.load(handle)) == {
            "cave_mouth": {"x": 0, "y": 0, "placed": False},
            "debris_room": {"x": 220, "y": 0, "placed": False},
            "grotto": {"x": 440, "y": 0, "placed": False}
        }


def test_place_loose():
    world = {"rooms": {"hall": {"x": 40, "y": 90}, "attic": {}, "cellar": {}}}
    assert writer.place(world) == {
        "hall": {"x": 40, "y": 90, "placed": True},
        "attic": {"x": 0, "y": 310, "placed": False},
        "cellar": {"x": 220, "y": 310, "placed": False}
    }


def test_place_half():
    assert writer.place({"rooms": {"hall": {"x": 40}}}) == {
        "hall": {"x": 0, "y": 0, "placed": False}}


def test_create_room(client, tmp_path):
    response = _send(client, "post", "/api/rooms",
                     room={"name": "Tunnel", "desc": "A tunnel."},
                     **{"from": {"room": "grotto", "dir": "north"}})
    assert response.status_code == 200
    rooms = _world(tmp_path)["rooms"]
    assert rooms["grotto"]["exits"]["north"] == "tunnel"
    assert rooms["tunnel"]["exits"]["south"] == "grotto"


def test_create_locked(client, tmp_path):
    assert _send(client, "post", "/api/rooms",
                 room={"name": "Vault", "desc": "A vault."},
                 **{"from": {"room": "grotto", "dir": "north",
                             "gate": "rubble_cleared"}}).status_code == 200
    grotto = _world(tmp_path)["rooms"]["grotto"]
    assert grotto["exits"]["north"] == "vault"
    assert grotto["requires"]["north"] == "rubble_cleared"


def test_way_back_open(client, tmp_path):
    _send(client, "post", "/api/rooms",
          room={"name": "Vault", "desc": "A vault."},
          **{"from": {"room": "grotto", "dir": "north", "gate": "rubble_cleared"}})
    assert "requires" not in _world(tmp_path)["rooms"]["vault"]


def test_create_placed(client, tmp_path):
    _send(client, "post", "/api/rooms",
          room={"name": "Tunnel", "desc": "A tunnel."},
          **{"from": {"room": "grotto", "dir": "north"}})
    tunnel = _world(tmp_path)["rooms"]["tunnel"]
    assert (tunnel["x"], tunnel["y"]) == (440, -220)


def test_create_below(client, tmp_path):
    _send(client, "post", "/api/rooms",
          room={"name": "Burrow", "desc": "A burrow."},
          **{"from": {"room": "grotto", "dir": "crawl"}})
    burrow = _world(tmp_path)["rooms"]["burrow"]
    assert (burrow["x"], burrow["y"]) == (440, 220)


def test_create_xy(client, tmp_path):
    """A body that carries a position is not second-guessed."""
    _send(client, "post", "/api/rooms",
          room={"name": "Tunnel", "desc": "A tunnel.", "x": 7, "y": 9},
          **{"from": {"room": "grotto", "dir": "north"}})
    tunnel = _world(tmp_path)["rooms"]["tunnel"]
    assert (tunnel["x"], tunnel["y"]) == (7, 9)


def test_create_abbrev(client, tmp_path):
    _send(client, "post", "/api/rooms",
          room={"name": "Tunnel", "desc": "A tunnel."},
          **{"from": {"room": "grotto", "dir": "n"}})
    rooms = _world(tmp_path)["rooms"]
    assert list(rooms["grotto"]["exits"]) == ["up", "north"]
    assert rooms["tunnel"]["exits"] == {"south": "grotto"}


def test_create_one_way(client, tmp_path):
    _send(client, "post", "/api/rooms",
          room={"name": "Pit", "desc": "A pit.", "oneway": True},
          **{"from": {"room": "grotto", "dir": "down", "reverse": False}})
    assert "exits" not in _world(tmp_path)["rooms"]["pit"]


def test_create_no_opposite(client, tmp_path):
    response = _send(client, "post", "/api/rooms",
                     room={"name": "Burrow", "desc": "A burrow."},
                     **{"from": {"room": "grotto", "dir": "crawl"}})
    assert response.status_code == 200
    assert _world(tmp_path)["rooms"]["grotto"]["exits"]["crawl"] == "burrow"
    assert "exits" not in _world(tmp_path)["rooms"]["burrow"]
    assert "burrow: no exits and not marked oneway" in (
        client.post("/api/validate").get_json()["warnings"])


def test_create_unconnected(client, tmp_path):
    """A room joined to nothing is unreachable, and the gate says so."""
    before = (tmp_path / "world" / "world.toml").read_bytes()
    response = _send(client, "post", "/api/rooms",
                     room={"name": "Attic", "desc": "An attic.", "oneway": True})
    assert response.status_code == 422
    assert response.get_json()["errors"] == ["unreachable rooms: attic"]
    assert (tmp_path / "world" / "world.toml").read_bytes() == before


def test_name_taken(client, tmp_path):
    response = _send(client, "post", "/api/rooms",
                     room={"name": "Grotto", "desc": "Another grotto."},
                     **{"from": {"room": "grotto", "dir": "north"}})
    assert response.status_code == 200
    assert response.get_json()["id"] == "grotto_2"
    assert _world(tmp_path)["rooms"]["grotto_2"]["name"] == "Grotto"


def test_put_keeps_xy(client, tmp_path):
    """A panel that does not show x and y must not throw them away."""
    _send(client, "put", "/api/layout", positions={"grotto": {"x": 40, "y": 90}})
    _send(client, "put", "/api/rooms/grotto",
          room={"name": "Grotto", "desc": "Changed.", "exits": {"up": "debris_room"}})
    grotto = _world(tmp_path)["rooms"]["grotto"]
    assert grotto["desc"] == "Changed."
    assert (grotto["x"], grotto["y"]) == (40, 90)


def test_rename_room(client, tmp_path):
    assert _send(client, "put", "/api/rooms/grotto",
                 room={"name": "Glitter hall", "desc": "A grotto.",
                       "exits": {"up": "debris_room"}}).status_code == 200
    world = _world(tmp_path)
    assert "grotto" not in world["rooms"]
    assert world["rooms"]["glitter_hall"]["name"] == "Glitter hall"
    assert world["rooms"]["debris_room"]["exits"]["down"] == "glitter_hall"
    assert list(world["rooms"]) == ["cave_mouth", "debris_room", "glitter_hall"]


def test_rename_start(client, tmp_path):
    _send(client, "put", "/api/rooms/cave_mouth",
          room={"name": "Cave entrance", "desc": "At the mouth.",
                "exits": {"in": "debris_room"}, "things": ["lamp", "shovel"]})
    assert _world(tmp_path)["meta"]["start"] == "cave_entrance"


def test_rename_thing(client, tmp_path):
    assert _send(client, "put", "/api/things/shovel",
                 thing={"name": "iron spade", "portable": True}).status_code == 200
    world = _world(tmp_path)
    assert "shovel" not in world["things"]
    assert world["rooms"]["cave_mouth"]["things"] == ["lamp", "iron_spade"]
    assert world["actions"]["dig_rubble"]["needs"] == ["iron_spade"]


def test_rename_taken(client, tmp_path):
    before = (tmp_path / "world" / "world.toml").read_bytes()
    response = _send(client, "put", "/api/rooms/grotto",
                     room={"name": "Debris room", "desc": "A grotto.",
                           "exits": {"up": "debris_room"}})
    assert response.status_code == 409
    assert response.get_json()["errors"] == [
        "There is already a room called debris_room."]
    assert (tmp_path / "world" / "world.toml").read_bytes() == before


def test_put_absent(client):
    response = _send(client, "put", "/api/rooms/nowhere",
                     room={"name": "Nowhere", "desc": "Nowhere."})
    assert response.status_code == 404
    assert response.get_json()["errors"] == ["There is no room called nowhere."]


def test_delete_room(client, tmp_path):
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


def test_delete_in_room(tmp_path):
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


SENDS = ('[meta]\ntitle = "A"\nstart = "hall"\nversion = 1\n\n'
         '[rooms.hall]\nname = "Hall"\ndesc = "A hall."\noneway = true\n'
         'things = ["box"]\n\n'
         '[rooms.attic]\nname = "Attic"\ndesc = "An attic."\noneway = true\n\n'
         '[things.box]\nname = "box"\n\n'
         '[actions.open_box]\nverb = "open"\nnoun = "box"\nin_room = "hall"\n'
         'goes = "attic"\nsets = ["opened"]\nmessage = "Open."\n')


def test_graph_goes(tmp_path):
    """An action's goes draws its own edge, from the room it fires in to the one it reaches."""
    graph = _client(lay_out(tmp_path, SENDS)).get("/api/graph").get_json()
    assert graph["goes"] == [
        {"from": "hall", "to": "attic", "verb": "open", "action": "open_box"}]


def test_delete_goes(tmp_path):
    """A room the player can be sent to is held in place as firmly as an exit holds it."""
    response = _send(_client(lay_out(tmp_path, SENDS)), "delete", "/api/rooms/attic")
    assert response.status_code == 409
    assert response.get_json()["errors"] == [
        "attic: action open_box sends the player there."]


def test_rename_goes(tmp_path):
    world = lay_out(tmp_path, SENDS)
    assert _send(_client(world), "put", "/api/rooms/attic",
                 room={"name": "Loft", "desc": "An attic.",
                       "oneway": True}).status_code == 200
    with open(world / "world.toml", "rb") as handle:
        saved = tomllib.load(handle)
    assert saved["actions"]["open_box"]["goes"] == "loft"


def test_put_keeps_formless(client, tmp_path):
    kept = {"art": "  ~~~  ", "also": [{"when": "lamp_lit", "desc": "Lit."}],
            "notes": [{"when": "lamp_lit", "line": "A note."}],
            "reasons": {"down": "Not yet."}}
    body = {"name": "Debris room", "desc": "A room full of debris.", "dark": True,
            "exits": {"out": "cave_mouth", "down": "grotto"},
            "requires": {"down": "rubble_cleared"}, "things": ["rubble"]}
    assert _send(client, "put", "/api/rooms/debris_room",
                 room=dict(body, **kept)).status_code == 200
    assert _send(client, "put", "/api/rooms/debris_room",
                 room=dict(body, desc="Debris, everywhere.")).status_code == 200
    room = _world(tmp_path)["rooms"]["debris_room"]
    assert room["desc"] == "Debris, everywhere."
    assert {key: room[key] for key in kept} == kept


def test_delete_reason(client, tmp_path):
    _send(client, "put", "/api/rooms/debris_room",
          room={"name": "Debris room", "desc": "A room full of debris.", "dark": True,
                "exits": {"out": "cave_mouth", "down": "grotto"},
                "requires": {"down": "rubble_cleared"}, "reasons": {"down": "Not yet."},
                "things": ["rubble"]})
    assert _send(client, "delete", "/api/rooms/grotto").status_code == 200
    assert _world(tmp_path)["rooms"]["debris_room"]["reasons"] == {}


def test_delete_unless(client, tmp_path):
    """A neighbour's way that could shut goes with the room it led to."""
    _send(client, "put", "/api/rooms/debris_room",
          room={"name": "Debris room", "desc": "A room full of debris.", "dark": True,
                "exits": {"out": "cave_mouth", "down": "grotto"},
                "unless": {"down": "lamp_lit"}, "things": ["rubble"]})
    assert _send(client, "delete", "/api/rooms/grotto").status_code == 200
    assert _world(tmp_path)["rooms"]["debris_room"]["unless"] == {}


def test_make_delete(client, tmp_path):
    before = _world(tmp_path)
    _send(client, "post", "/api/rooms",
          room={"name": "Tunnel", "desc": "A tunnel."},
          **{"from": {"room": "grotto", "dir": "north"}})
    assert _send(client, "delete", "/api/rooms/tunnel").status_code == 200
    assert _world(tmp_path) == before


def test_delete_used_thing(client):
    response = _send(client, "delete", "/api/things/lamp")
    assert response.status_code == 409
    assert response.get_json()["errors"] == ["lamp: action light_lamp uses it."]


def test_delete_thing(client, tmp_path):
    assert _send(client, "post", "/api/things",
                 thing={"name": "a coin"}).get_json()["id"] == "a_coin"
    _send(client, "put", "/api/rooms/grotto",
          room={"name": "Grotto", "desc": "A grotto.",
                "exits": {"up": "debris_room"}, "things": ["a_coin"]})
    assert _world(tmp_path)["rooms"]["grotto"]["things"] == ["a_coin"]
    assert _send(client, "delete", "/api/things/a_coin").status_code == 200
    assert _world(tmp_path)["rooms"]["grotto"]["things"] == []
    assert "a_coin" not in _world(tmp_path)["things"]


def test_actions_crud(client, tmp_path):
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


def test_meta_ending(client, tmp_path):
    """The world panel can set the game's ending flag, and remove it again."""
    _send(client, "put", "/api/meta", meta={"title": "U", "start": "cave_mouth",
                                            "ending": "rubble_cleared"})
    assert _world(tmp_path)["meta"]["ending"] == "rubble_cleared"
    _send(client, "put", "/api/meta", meta={"title": "U", "start": "cave_mouth",
                                            "ending": ""})
    assert "ending" not in _world(tmp_path)["meta"]


def test_meta(client, tmp_path):
    assert _send(client, "put", "/api/meta",
                 meta={"title": "Over the Hill", "start": "grotto", "version": 2}
                 ).status_code == 200
    meta = _world(tmp_path)["meta"]
    assert (meta["title"], meta["start"], meta["version"]) == (
        "Over the Hill", "grotto", 1)


def test_marks(client, tmp_path):
    _send(client, "put", "/api/marks",
          marks={"attention": {"threshold": 2, "sets": "watched"}})
    assert _world(tmp_path)["marks"]["attention"] == {"threshold": 2, "sets": "watched"}
    _send(client, "put", "/api/marks", marks={})
    assert "marks" not in _world(tmp_path)


def test_mark_zero(client, tmp_path):
    """The validator's floor holds through the editor: a threshold must be positive."""
    before = (tmp_path / "world" / "world.toml").read_bytes()
    response = _send(client, "put", "/api/marks",
                     marks={"attention": {"threshold": 0, "sets": "watched"}})
    assert response.status_code == 422
    assert (tmp_path / "world" / "world.toml").read_bytes() == before


def test_layout(client, tmp_path):
    assert _send(client, "put", "/api/layout",
                 positions={"grotto": {"x": 12.6, "y": -3.2}}).status_code == 200
    grotto = _world(tmp_path)["rooms"]["grotto"]
    assert (grotto["x"], grotto["y"]) == (13, -3)


def test_layout_grid(client):
    """A single placed room pushes every unplaced one a row underneath it."""
    _send(client, "put", "/api/layout", positions={"grotto": {"x": 12.6, "y": -3.2}})
    spots = {node["id"]: (node["x"], node["y"], node["placed"])
             for node in client.get("/api/graph").get_json()["nodes"]}
    assert spots == {"cave_mouth": (0, 217, False), "debris_room": (220, 217, False),
                     "grotto": (13, -3, True)}


def test_layout_absent(client):
    response = _send(client, "put", "/api/layout", positions={"nowhere": {"x": 1, "y": 2}})
    assert response.status_code == 404


def test_write_gate(client, tmp_path):
    before = (tmp_path / "world" / "world.toml").read_bytes()
    response = _send(client, "put", "/api/rooms/grotto",
                     room={"name": "Grotto", "desc": "A grotto.",
                           "exits": {"up": "debris_room", "north": "nowhere"}})
    assert response.status_code == 422
    assert response.get_json()["errors"] == [
        "grotto: exit north leads to unknown room nowhere"]
    assert (tmp_path / "world" / "world.toml").read_bytes() == before


def test_stale(client, tmp_path):
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
def test_no_mtime(method, url, client):
    response = getattr(client, method)(url, json={
        "id": "attic", "room": {"name": "Attic", "desc": "An attic."}})
    assert response.status_code == 400
    assert response.get_json()["errors"] == [
        "The request body is not the shape this route takes."]


def test_roundtrip(tmp_path):
    world = lay_out(tmp_path, '# The world above the hill.\n[meta]\ntitle = "A"\n'
                     'start = "hall"\nversion = 1\n\n'
                     '# The only room.\n[rooms.hall]\nname = "Hall"\n'
                     'desc = "A hall."\noneway = true\n')
    _send(_client(world), "put", "/api/layout", positions={"hall": {"x": 1, "y": 2}})
    written = (world / "world.toml").read_text()
    assert "# The world above the hill." in written
    assert "# The only room." in written
    assert written.index("name") < written.index("desc") < written.index("x = 1")
