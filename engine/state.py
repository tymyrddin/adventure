"""Fresh games, saving, restoring and content hashing."""

import hashlib
import json

from engine.world import StateError


def new_game(world):
    """Return a fresh game dict for a world, remembering the file it was read from."""
    return {
        "location": world["meta"]["start"],
        "inventory": [],
        "flags": set(),
        "fired": set(),
        "moves": 0,
        "marks": {},
        "placements": {name: list(room.get("things", []))
                       for name, room in world["rooms"].items()},
        "source": world["words"]["source"],
        "over": False,
    }


def save(game, path):
    """Write the game and the hash of its world file to path as JSON."""
    payload = {
        "game": dict(game, flags=sorted(game["flags"]), fired=sorted(game["fired"])),
        "world_hash": content_hash(game["source"]),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def restore(path, world_hash, said):
    """Return the game held in a save file, or raise StateError in the world's words."""
    try:
        with open(path, "rb") as handle:
            payload = json.load(handle)
    except OSError as missing:
        raise StateError(said["save_missing"]) from missing
    except json.JSONDecodeError as unreadable:
        raise StateError(said["save_mismatch"]) from unreadable
    if not isinstance(payload, dict) or payload.get("world_hash") != world_hash:
        raise StateError(said["save_mismatch"])
    try:
        game = payload["game"]
        game["flags"] = set(game["flags"])
        game["fired"] = set(game["fired"])
    except (KeyError, TypeError) as malformed:
        raise StateError(said["save_mismatch"]) from malformed
    return game


def content_hash(path):
    """Return the SHA-256 hex digest of the file's bytes."""
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()
