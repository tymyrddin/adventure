"""Round-trip reading, atomic writing and map placement for the world file."""

import os
import tempfile

import tomlkit

COLUMNS = 5
SPACING = 220


def read(path):
    """Return the file at path as a tomlkit document, comments and order intact."""
    with open(path, encoding="utf-8") as handle:
        return tomlkit.parse(handle.read())


def write(doc, path):
    """Replace path with doc, written first to a temporary file beside it."""
    handle, temporary = tempfile.mkstemp(
        dir=os.path.dirname(os.path.abspath(path)), suffix=".toml")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(tomlkit.dumps(doc))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return os.stat(path).st_mtime


def check_mtime(path, seen):
    """Return whether the file at path still carries the modification time seen."""
    return os.stat(path).st_mtime == seen


def place(world):
    """Return {room: {x, y, placed}} for every room."""
    rooms = _rooms(world)
    placed = {name: {"x": room["x"], "y": room["y"], "placed": True}
              for name, room in rooms.items() if _positioned(room)}
    bottom = max((spot["y"] for spot in placed.values()), default=None)
    origin = 0 if bottom is None else bottom + SPACING
    grid = {name: {"x": SPACING * (index % COLUMNS),
                   "y": origin + SPACING * (index // COLUMNS), "placed": False}
            for index, name in enumerate(
                name for name in rooms if name not in placed)}
    return {name: placed.get(name, grid.get(name)) for name in rooms}


def _positioned(room):
    """Return whether a room carries both coordinates, as integers and not booleans."""
    return all(isinstance(room.get(key), int) and not isinstance(room.get(key), bool)
               for key in ("x", "y"))


def _rooms(world):
    """Return the rooms table in file order, skipping anything malformed."""
    rooms = world.get("rooms", {})
    if not isinstance(rooms, dict):
        return {}
    return {name: room for name, room in rooms.items() if isinstance(room, dict)}
