"""Flask editor for a world file."""

import os
import pathlib
import tomllib

import tomlkit
from flask import Flask, jsonify, render_template, request
from tomlkit.exceptions import ParseError

from editor import writer
from engine import data
from engine.world import reachable_from, solvable, validate

_BELOW = [0, 1]
_SINGULAR = {"rooms": "room", "things": "thing", "actions": "action"}


def _words(path):
    """Return the data bound to the world this file belongs to, read afresh."""
    return data.load(pathlib.Path(path).parent)


def create_app(world):
    """Return the editor app for the world in this directory."""
    app = Flask(__name__)
    app.json.sort_keys = False  # type: ignore[attr-defined]
    words = data.load(world)
    path = str(pathlib.Path(world) / words["builtins"]["files"]["world"])
    _read_routes(app, path)
    _record_routes(app, path, "rooms", _insert_room, _remove_room)
    _record_routes(app, path, "things",
                   lambda doc, body, words: _insert(doc, "things", body, words),
                   _remove_thing)
    _record_routes(app, path, "actions",
                   lambda doc, body, words: _insert(doc, "actions", body, words),
                   _remove_action)
    _world_routes(app, path)
    return app


def _read_routes(app, path):
    """Register the routes that only report what the file says."""

    @app.get("/")
    def index():
        """Render the page the map is drawn on."""
        world, unparsable = _read(path)
        title = "" if unparsable else _get(_get(world, "meta", {}), "title", "")
        return render_template("index.html", source=path, title=title,
                               unparsable=unparsable)

    @app.get("/api/world")
    def api_world():
        """Return the whole world file as JSON, with its modification time."""
        world, unparsable = _read(path)
        if unparsable:
            return jsonify({"errors": [unparsable]}), 422
        return jsonify({"world": world, "mtime": os.stat(path).st_mtime})

    @app.post("/api/validate")
    def api_validate():
        """Return the errors, the warnings and the solvability waves."""
        world, unparsable = _read(path)
        if unparsable:
            return jsonify({"errors": [unparsable], "warnings": [], "waves": []})
        errors, warnings = validate(world, _words(path))
        return jsonify({"errors": errors, "warnings": warnings,
                        "waves": solvable(world)[2]})

    @app.get("/api/graph")
    def api_graph():
        """Return the nodes and the edges."""
        world, unparsable = _read(path)
        if unparsable:
            return jsonify({"errors": [unparsable]}), 422
        return jsonify(_graph(world, _words(path)))


def _record_routes(app, path, table, insert, remove):
    """Register create, replace and delete for one of the id tables."""

    def create():
        """Create one record from the id and the record the body carries."""
        return _change(path, insert)

    def replace(name):
        """Replace one record."""
        return _change(path, lambda doc, body, words:
                       _replace(doc, table, name, body, words))

    def delete(name):
        """Delete one record, with the refusals."""
        return _change(path, lambda doc, _body, words: remove(doc, name, words))

    singular = _SINGULAR[table]
    app.add_url_rule(f"/api/{table}", f"create_{singular}", create, methods=["POST"])
    app.add_url_rule(f"/api/{table}/<name>", f"replace_{singular}", replace,
                     methods=["PUT"])
    app.add_url_rule(f"/api/{table}/<name>", f"delete_{singular}", delete,
                     methods=["DELETE"])


def _world_routes(app, path):
    """Register the two routes that write something other than one record."""

    @app.put("/api/meta")
    def api_meta():
        """Replace the title and the start room."""
        return _change(path, _set_meta)

    @app.put("/api/layout")
    def api_layout():
        """Write the coordinates of every room the author moved."""
        return _change(path, _set_layout)

    @app.put("/api/marks")
    def api_marks():
        """Replace the whole marks table with the ones the world panel holds."""
        return _change(path, _set_marks)


def _change(path, apply):
    """Run one write: the mtime check, the change, the validation gate, the file."""
    words = _words(path)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("mtime"), (int, float)):
        return _refuse(words, "bad_request", 400)
    try:
        doc = writer.read(path)
    except OSError as missing:
        return jsonify({"errors": [str(missing)]}), 422
    except ParseError as unparsable:
        return jsonify({"errors": [str(unparsable)]}), 422
    if not writer.check_mtime(path, body["mtime"]):
        return _refuse(words, "stale", 409)
    refusal = apply(doc, body, words)
    if refusal is not None:
        return refusal
    errors, _warnings = validate(doc.unwrap(), words)
    if errors:
        return jsonify({"errors": errors}), 422
    return jsonify({"mtime": writer.write(doc, path), "id": body.get("id")})


def _slug(said, charset):
    """Return words as a bare key, by the id charset the world's schema declares."""
    kept = "".join(letter if letter in charset else " " for letter in said.lower())
    return "_".join(kept.split())


def _identity(table, record, words):
    """Return the id a record's own naming fields spell."""
    charset = frozenset(words["schema"]["id_chars"])
    if table == "actions":
        return _slug(f"{_get(record, 'verb', '')} {_get(record, 'noun', '')}", charset)
    return _slug(_get(record, "name", ""), charset)


def _free(records, wanted, kind):
    """Return wanted, stepped past anything already there, or a numbered fallback."""
    for number in range(1, 1000):
        candidate = (wanted or kind) if number == 1 else f"{wanted or kind}_{number}"
        if candidate not in records:
            return candidate
    return wanted


def _insert(doc, table, body, words):
    """Add one record under the id its name spells."""
    record = body.get(_SINGULAR[table])
    if not isinstance(record, dict):
        return _refuse(words, "bad_request", 400)
    name = _free(_table(doc, table), _identity(table, record, words), _SINGULAR[table])
    if table == "actions" and not _get(record, "sets", []):
        record["sets"] = [name]
    if table != "actions" and not _get(record, "name", ""):
        record["name"] = name
    body["id"] = name
    _writable(doc, table)[name] = record
    return None


def _insert_room(doc, body, words):
    """Add a room, and the exits that join it to the room it was made from."""
    refusal = _insert(doc, "rooms", body, words)
    return refusal if refusal is not None else _connect(doc, body, words)


def _connect(doc, body, words):
    """Add the exit from the source room, and the reverse exit back."""
    source = body.get("from")
    if source is None:
        return None
    rooms = _table(doc, "rooms")
    if not isinstance(source, dict) or not isinstance(source.get("dir"), str):
        return _refuse(words, "bad_request", 400)
    if source.get("room") not in rooms:
        return _refuse(words, "no_such", 404, table="room", id=source.get("room"))
    direction = words["builtins"]["directions"].get(source["dir"], source["dir"])
    _exits(rooms[source["room"]])[direction] = body["id"]
    if source.get("gate"):
        _gates(rooms[source["room"]], "requires")[direction] = source["gate"]
    if source.get("holds"):
        _gates(rooms[source["room"]], "holding")[direction] = source["holds"]
    opposite = words["builtins"]["opposites"].get(direction)
    if opposite is not None and source.get("reverse", True):
        _exits(rooms[body["id"]])[opposite] = source["room"]
    _offset(rooms, body["id"], source["room"], direction, words)
    return None


def _offset(rooms, name, source, direction, words):
    """Position a new room one spacing from the one it was made from."""
    room = rooms[name]
    if "x" in room and "y" in room:
        return
    spots = writer.place({"rooms": rooms})
    across, down = words["builtins"]["offsets"].get(direction, _BELOW)
    room["x"] = spots[source]["x"] + across * writer.SPACING
    room["y"] = spots[source]["y"] + down * writer.SPACING


def _replace(doc, table, name, body, words):
    """Replace one record, keeping a room's coordinates when the body omits them."""
    records = _table(doc, table)
    record = body.get(_SINGULAR[table])
    if name not in records:
        return _refuse(words, "no_such", 404, table=_SINGULAR[table], id=name)
    if not isinstance(record, dict):
        return _refuse(words, "bad_request", 400)
    if table == "rooms":
        record = dict(record, **{key: records[name][key] for key in ("x", "y")
                                 if key in records[name] and key not in record})
    records[name] = record
    wanted = _identity(table, record, words)
    if not wanted or wanted == name:
        return None
    if wanted in records:
        return _refuse(words, "id_taken", 409, table=_SINGULAR[table], id=wanted)
    _rekey(records, name, wanted)
    _repoint(doc, table, name, wanted)
    return None


def _rekey(records, old, new):
    """Rename one key of a table, leaving the file's order as it was."""
    kept = [(new if key == old else key, value) for key, value in records.items()]
    for key in list(records):
        del records[key]
    for key, value in kept:
        records[key] = value


def _repoint(doc, table, old, new):
    """Rewrite everything that named the record by its old id."""
    rooms = _table(doc, "rooms")
    if table == "rooms":
        for _name, room in _records(rooms):
            for direction, target in list(_get(room, "exits", {}).items()):
                if target == old:
                    room["exits"][direction] = new
        for _id, action in _records(_table(doc, "actions")):
            if action.get("in_room") == old:
                action["in_room"] = new
            if action.get("goes") == old:
                action["goes"] = new
        if _get(_table(doc, "meta"), "start", "") == old:
            doc["meta"]["start"] = new
    if table == "things":
        for _name, room in _records(rooms):
            held = _get(room, "things", [])
            for index, thing in enumerate(list(held)):
                if thing == old:
                    held[index] = new
        for _id, action in _records(_table(doc, "actions")):
            if action.get("noun") == old:
                action["noun"] = new
            needs = _get(action, "needs", [])
            for index, thing in enumerate(list(needs)):
                if thing == old:
                    needs[index] = new


def _remove_room(doc, name, words):
    """Delete a room and the exits that led to it, refusing while an action names it."""
    rooms = _table(doc, "rooms")
    if name not in rooms:
        return _refuse(words, "no_such", 404, table="room", id=name)
    for action, record in _records(_table(doc, "actions")):
        if record.get("in_room") == name:
            return _refuse(words, "room_in_action", 409, room=name, action=action)
        if record.get("goes") == name:
            return _refuse(words, "room_in_goes", 409, room=name, action=action)
    for source, room in _records(rooms):
        if source != name:
            _drop_exits(room, name)
    del rooms[name]
    return None


def _drop_exits(room, target):
    """Remove one room's exits to target, and every gate and hiding said of them."""
    for direction in [way for way, to in _get(room, "exits", {}).items()
                      if to == target]:
        del room["exits"][direction]
        for key in ("requires", "holding", "unless"):
            if direction in _get(room, key, {}):
                del room[key][direction]
        while direction in _get(room, "hidden", []):
            room["hidden"].remove(direction)


def _remove_thing(doc, name, words):
    """Delete a thing and its placement, refusing while an action uses it."""
    things = _table(doc, "things")
    if name not in things:
        return _refuse(words, "no_such", 404, table="thing", id=name)
    for action, record in _records(_table(doc, "actions")):
        if record.get("noun") == name or name in _get(record, "needs", []):
            return _refuse(words, "thing_in_action", 409, thing=name, action=action)
    for _room, record in _records(_table(doc, "rooms")):
        held = _get(record, "things", [])
        while name in held:
            held.remove(name)
    del things[name]
    return None


def _remove_action(doc, name, words):
    """Delete an action; what its absence breaks is the validation gate's business."""
    actions = _table(doc, "actions")
    if name not in actions:
        return _refuse(words, "no_such", 404, table="action", id=name)
    del actions[name]
    return None


def _set_marks(doc, body, words):
    """Replace [marks] with the named counters the body carries, or clear it."""
    marks = body.get("marks")
    if not isinstance(marks, dict):
        return _refuse(words, "bad_request", 400)
    for spec in marks.values():
        if not isinstance(spec, dict) or not isinstance(spec.get("threshold"), int) \
                or isinstance(spec.get("threshold"), bool) \
                or not isinstance(spec.get("sets"), str):
            return _refuse(words, "bad_request", 400)
    if marks:
        table = _writable(doc, "marks")
        for name in list(table):
            del table[name]
        for name, spec in marks.items():
            table[name] = {"threshold": spec["threshold"], "sets": spec["sets"]}
    elif "marks" in doc:
        del doc["marks"]
    return None


def _set_meta(doc, body, words):
    """Replace the writable keys of [meta]; the version is not one of them."""
    record = body.get("meta")
    if not isinstance(record, dict):
        return _refuse(words, "bad_request", 400)
    meta = _writable(doc, "meta", False)
    for key in ("title", "start"):
        if key in record:
            meta[key] = record[key]
    if "ending" in record:
        if record["ending"]:
            meta["ending"] = record["ending"]
        elif "ending" in meta:
            del meta["ending"]
    return None


def _set_layout(doc, body, words):
    """Write x and y for every room the body names, rounded to integers."""
    positions = body.get("positions")
    rooms = _table(doc, "rooms")
    if not isinstance(positions, dict):
        return _refuse(words, "bad_request", 400)
    for name, spot in positions.items():
        if name not in rooms:
            return _refuse(words, "no_such", 404, table="room", id=name)
        if not isinstance(spot, dict) or not all(
                isinstance(spot.get(key), (int, float)) for key in ("x", "y")):
            return _refuse(words, "bad_request", 400)
        rooms[name]["x"] = round(spot["x"])
        rooms[name]["y"] = round(spot["y"])
    return None


def _read(path):
    """Return (world, None), or (None, message) when the file will not be read."""
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle), None
    except OSError as missing:
        return None, str(missing)
    except tomllib.TOMLDecodeError as unparsable:
        return None, str(unparsable)


def _graph(world, words):
    """Return the nodes and the edges, in file order."""
    rooms = _get(world, "rooms", {})
    meta = _get(world, "meta", {})
    start = _get(meta, "start", "")
    connected = reachable_from(world, start)
    waves = solvable(world)[2]
    wave_of = {room: number for number, wave in enumerate(waves, 1)
               for room in wave["rooms"]}
    spots = writer.place(world)
    nodes = [{"id": name, "name": _get(room, "name", name),
              "reachable": name in connected, "wave": wave_of.get(name),
              "dark": _get(room, "dark", False), "start": name == start,
              **spots[name]}
             for name, room in _records(rooms)]
    edges = [{"from": name, "to": target, "dir": direction,
              "gate": _get(room, "requires", {}).get(direction),
              "holds": _get(room, "holding", {}).get(direction),
              "hidden": direction in _get(room, "hidden", []),
              "shuts": _get(room, "unless", {}).get(direction),
              "pair": _pair(rooms, name, direction, target, words)}
             for name, room in _records(rooms)
             for direction, target in _get(room, "exits", {}).items()
             if target in rooms]
    goes = [{"from": action.get("in_room"), "to": action["goes"],
             "verb": _get(action, "verb", ""), "action": name}
            for name, action in _records(_get(world, "actions", {}))
            if isinstance(action.get("goes"), str) and action["goes"] in rooms]
    return {"nodes": nodes, "edges": edges, "goes": goes}


def _pair(rooms, name, direction, target, words):
    """Return the id the two halves of a reciprocal exit share, or None."""
    opposite = words["builtins"]["opposites"].get(direction)
    back = _get(_get(rooms, target, {}), "exits", {}).get(opposite)
    if opposite is None or back != name:
        return None
    if _stopped(rooms[name], direction) or _stopped(_get(rooms, target, {}), opposite):
        return None
    return "|".join(sorted([name, target]) + sorted([direction, opposite]))


def _stopped(room, direction):
    """Return whether a direction is conditional, or hidden from the exits line."""
    return (direction in _get(room, "requires", {})
            or direction in _get(room, "holding", {})
            or direction in _get(room, "hidden", []))


def _exits(room):
    """Return a room's exits, adding an empty inline table when it has none."""
    if not isinstance(room.get("exits"), dict):
        room["exits"] = tomlkit.inline_table()
    return room["exits"]


def _gates(room, key):
    """Return a room's requires or holding, adding an empty table when it has none."""
    if not isinstance(room.get(key), dict):
        room[key] = tomlkit.inline_table()
    return room[key]


def _writable(doc, name, super_table=True):
    """Return a top-level table, adding an empty one when the file has none."""
    if not isinstance(doc.get(name), dict):
        doc[name] = tomlkit.table(super_table)
    return doc[name]


def _refuse(words, name, status, **fields):
    """Return the body and the status of one refusal."""
    said = words["reports"]["editor"][name].format(**fields)
    return jsonify({"errors": [said]}), status


def _table(doc, name):
    """Return a top-level table, or an empty one when it is absent or malformed."""
    return _get(doc, name, {})


def _records(rooms):
    """Return the (id, record) pairs of a table, skipping malformed records."""
    return [(name, room) for name, room in rooms.items() if isinstance(room, dict)]


def _get(record, key, default):
    """Return record[key] when it matches the default's type, otherwise the default."""
    value = record.get(key, default)
    return value if isinstance(value, type(default)) else default
