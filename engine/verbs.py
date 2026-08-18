"""Playing a turn, and describing where the player stands."""

import pathlib

from engine import state as state_module
from engine.world import StateError, many


def _builtins(world):
    """Return the vocabulary bound to this world."""
    return world["words"]["builtins"]


def _verbs(world):
    """Return this world's built-in verbs and their properties."""
    return world["words"]["builtins"]["verbs"]


def perform(world, game, line):
    """Return the complete output for one command line, without a trailing newline."""
    words = _parse(world, line)
    if not words:
        return ""
    noun = words[1] if len(words) > 1 else None
    if not _is_known(world, words[0], noun):
        return _text(world, "unknown_verb", word=words[0])
    if noun is not None and not _verbs(world).get(words[0], {}).get(
            "takes_direction", False):
        noun, confused = _resolve(world, game, noun)
        if confused is not None:
            return confused
    game["moves"] += 1
    spoken = _dispatch(world, game, words[0], noun)
    if world["meta"].get("ending") in game["flags"]:
        game["over"] = True
    return spoken


def describe(world, game):
    """Return the room description, or the darkness line."""
    room = world["rooms"][game["location"]]
    if not _lit(world, game):
        return _text(world, "pitch_dark")
    lines = [room["name"], "", room["desc"]]
    here = game["placements"][game["location"]]
    if here:
        lines.append(_text(world, "you_can_see",
                           things=", ".join(world["things"][t]["name"] for t in here)))
    shown = _visible_exits(game, room)
    if shown:
        lines.append(_text(world, "exits", exits=", ".join(shown)))
    return "\n".join(lines)


def _parse(world, line):
    """Return the verb and, joined into one id, everything the player said after it."""
    words = [word for word in line.lower().split()
             if word not in _builtins(world)["articles"]]
    if not words:
        return []
    words[0] = world.get("synonyms", {}).get(words[0], words[0])
    words[0] = _builtins(world)["abbreviations"].get(words[0], words[0])
    return words[:1] if len(words) == 1 else [words[0], "_".join(words[1:])]


def _resolve(world, game, noun):
    """Return the thing these words name here, or the question when several fit."""
    here = game["placements"][game["location"]] + game["inventory"]
    if noun in here:
        return noun, None
    said = set(noun.split("_"))
    fits = [thing for thing in here if said <= _words_for(world, thing)]
    if len(fits) > 1:
        return None, _text(world, "which_one", things=", ".join(
            world["things"][thing]["name"] for thing in fits))
    return (fits[0] if fits else noun), None


def _words_for(world, thing):
    """Return every word that names a thing: its id, and the name a player reads."""
    return set(thing.split("_")) | set(world["things"][thing]["name"].lower().split())


def _spoken(noun):
    """Return a noun id as the player would have typed it, in words."""
    return noun.replace("_", " ")


def _is_known(world, verb, noun):
    """Say whether the parser recognises this verb at all."""
    if verb in _verbs(world) and verb in _HANDLERS:
        return True
    if noun is None and _is_direction(world, verb):
        return True
    return _is_action_verb(world, verb)


def _dispatch(world, game, verb, noun):
    """Return the output for a recognised verb."""
    if verb in _verbs(world):
        return _builtin(world, game, verb, noun)
    if noun is None and _is_direction(world, verb):
        return _move(world, game, verb)
    if noun is None:
        return _text(world, "needs_noun", verb=verb.capitalize())
    if not _visible(game, noun):
        return _text(world, "no_such_thing", noun=_spoken(noun))
    return _do_action(world, game, verb, noun)


def _builtin(world, game, verb, noun):
    """Return the output for a built-in verb, after the noun and darkness checks."""
    spec = _verbs(world)[verb]
    if noun is None and spec.get("needs_noun", False):
        return _text(world, "needs_direction" if spec.get("takes_direction", False)
                     else "needs_noun", verb=verb.capitalize())
    if spec.get("dark_blocks", False) and not _lit(world, game):
        return _text(world, "too_dark")
    if noun is not None and not spec.get("takes_direction", False) \
            and not _visible(game, noun):
        return _text(world, "no_such_thing", noun=_spoken(noun))
    return _HANDLERS[verb](world, game, noun)


def _look(world, game, noun):
    """Describe the room again."""
    return describe(world, game)


def _go(world, game, noun):
    """Move in the named direction."""
    return _move(world, game, noun)


def _move(world, game, direction):
    """Move through an exit, or report that there is no way or that it is blocked."""
    direction = _builtins(world)["directions"].get(direction, direction)
    room = world["rooms"][game["location"]]
    exits = room.get("exits", {})
    if direction not in exits:
        return _text(world, "no_way", dir=direction)
    gate = room.get("requires", {}).get(direction)
    if gate is not None and not set(many(gate)) <= game["flags"]:
        return _text(world, "blocked", dir=direction)
    carried = room.get("holding", {}).get(direction)
    if carried is not None and not set(many(carried)) <= set(game["inventory"]):
        return _text(world, "blocked", dir=direction)
    shut = room.get("unless", {}).get(direction)
    if shut is not None and set(many(shut)) & game["flags"]:
        return _text(world, "shut", dir=direction)
    game["location"] = exits[direction]
    return describe(world, game)


def _passable(game, room, direction):
    """Say whether an exit would let the player through right now."""
    gate = room.get("requires", {}).get(direction)
    if gate is not None and not set(many(gate)) <= game["flags"]:
        return False
    carried = room.get("holding", {}).get(direction)
    if carried is not None and not set(many(carried)) <= set(game["inventory"]):
        return False
    shut = room.get("unless", {}).get(direction)
    return shut is None or not set(many(shut)) & game["flags"]


def _visible_exits(game, room):
    """Return the ways out worth listing: the plain ones, and hidden ones now open."""
    hidden = room.get("hidden", [])
    return [direction for direction in room.get("exits", {})
            if direction not in hidden or _passable(game, room, direction)]


def _take(world, game, noun):
    """Move a portable thing from the room to the inventory."""
    here = game["placements"][game["location"]]
    if noun not in here:
        return _text(world, "no_effect")
    if not world["things"][noun].get("portable", False):
        return _text(world, "not_portable")
    here.remove(noun)
    game["inventory"].append(noun)
    return _text(world, "taken")


def _drop(world, game, noun):
    """Move a carried thing from the inventory to the room."""
    if noun not in game["inventory"]:
        return _text(world, "no_effect")
    game["inventory"].remove(noun)
    game["placements"][game["location"]].append(noun)
    return _text(world, "dropped")


def _examine(world, game, noun):
    """Return a thing's description."""
    return world["things"][noun].get("desc", _text(world, "nothing_special"))


def _inventory(world, game, noun):
    """List what the player is carrying, in the order it was taken."""
    if not game["inventory"]:
        return _text(world, "carrying_nothing")
    names = ", ".join(world["things"][t]["name"] for t in game["inventory"])
    return _text(world, "carrying", things=names)


def _save(world, game, noun):
    """Write the save file beside the world file."""
    state_module.save(game, _save_path(world, game))
    return _text(world, "saved")


def _load(world, game, noun):
    """Restore the save file beside the world file, replacing the game in place."""
    try:
        restored = state_module.restore(_save_path(world, game),
                                        state_module.content_hash(game["source"]),
                                        world["words"]["messages"]["player"])
    except StateError as refused:
        return str(refused)
    restored["source"] = game["source"]
    game.clear()
    game.update(restored)
    return _text(world, "loaded") + "\n" + describe(world, game)


def _quit(world, game, noun):
    """End the game."""
    game["over"] = True
    return _text(world, "goodbye")


def _help(world, game, noun):
    """List what can be typed from where the player is standing."""
    room = world["rooms"][game["location"]]
    shown = _visible_exits(game, room)
    lines = []
    if shown:
        lines.append(_text(world, "help_exits", dirs=", ".join(shown)))
    for verb, nouns in _to_hand(world, game):
        lines.append(_text(world, "help_verb", verb=verb, nouns=", ".join(nouns)))
    lines.append(_text(world, "help_always", verbs=", ".join(_free_verbs(world))))
    pairs = [_text(world, "help_pair", short=short, long=long)
             for short, long in _builtins(world)["abbreviations"].items()]
    return "\n".join(lines + [_text(world, "help_short", short=", ".join(pairs))])


def _to_hand(world, game):
    """Return each verb with the things here it can be used on, in dispatch order."""
    here = game["placements"][game["location"]]
    carried = game["inventory"]
    lit = _lit(world, game)
    offered = [
        ("take", [t for t in here if world["things"][t].get("portable", False)]),
        ("drop", list(carried)),
        ("examine", here + carried),
    ]
    pairs = [(verb, [_spoken(t) for t in things])
             for verb, things in offered
             if things and _usable(world, verb, lit)]
    return pairs + _world_verbs(world, game, here + carried)


def _usable(world, verb, lit):
    """Say whether a built-in verb can be used in the light there is."""
    return lit or not _verbs(world)[verb].get("dark_blocks", False)


def _world_verbs(world, game, seen):
    """Return this world's own verbs, with the things here they can be used on."""
    found = {}
    for action in world.get("actions", {}).values():
        where = action.get("in_room")
        if action["noun"] in seen and where in (None, game["location"]):
            found.setdefault(action["verb"], []).append(_spoken(action["noun"]))
    return list(found.items())


def _free_verbs(world):
    """Return the built-in verbs that need nothing to act on."""
    return [verb for verb, spec in _verbs(world).items()
            if not spec.get("needs_noun", False)]


def _do_action(world, game, verb, noun):
    """Run the action matching (verb, noun), or report that nothing happens."""
    for name, action in world.get("actions", {}).items():
        if (action["verb"], action["noun"]) != (verb, noun):
            continue
        if name in game["fired"]:
            return _text(world, "already_done")
        if not _conditions_met(game, action):
            return _text(world, "no_effect")
        game["flags"].update(action["sets"])
        _spends(game, action)
        _raises(world, game, action)
        if action.get("once", True):
            game["fired"].add(name)
        return action["message"]
    return _text(world, "no_effect")


def _spends(game, action):
    """Remove what the action used up: a thing spent is gone, not carried."""
    for thing in action.get("spends", []):
        while thing in game["inventory"]:
            game["inventory"].remove(thing)


def _raises(world, game, action):
    """Add to what this action leaves behind, and remember any threshold it crosses."""
    for mark, amount in action.get("raises", {}).items():
        game["marks"][mark] = game["marks"].get(mark, 0) + amount
        record = world.get("marks", {}).get(mark)
        if record and game["marks"][mark] >= record["threshold"]:
            game["flags"].add(record["sets"])


def _conditions_met(game, action):
    """Say whether the room, the inventory and the flags satisfy an action."""
    if action.get("in_room") not in (None, game["location"]):
        return False
    if not set(action.get("needs", [])) <= set(game["inventory"]):
        return False
    return set(action.get("when", [])) <= game["flags"]


def _lit(world, game):
    """Say whether the current room is illuminated."""
    if not world["rooms"][game["location"]].get("dark", False):
        return True
    for thing in game["placements"][game["location"]] + game["inventory"]:
        record = world["things"][thing]
        if "light_when" in record and record["light_when"] in game["flags"]:
            return True
    return False


def _visible(game, noun):
    """Say whether a thing id names something in the room or the inventory."""
    return noun in game["placements"][game["location"]] or noun in game["inventory"]


def _is_direction(world, word):
    """Say whether a word names a direction in this world."""
    fixed = _builtins(world)["directions"]
    if word in fixed or word in fixed.values():
        return True
    return any(word in room.get("exits", {}) for room in world["rooms"].values())


def _is_action_verb(world, verb):
    """Say whether any action uses this verb."""
    return any(action["verb"] == verb for action in world.get("actions", {}).values())


def _save_path(world, game):
    """Return the save file's path, beside the world file."""
    return pathlib.Path(game["source"]).parent / _builtins(world)["files"]["save"]


def _text(world, name, **fields):
    """Return one player-facing line."""
    return world["words"]["messages"]["player"][name].format(**fields)


_HANDLERS = {
    "look": _look,
    "go": _go,
    "take": _take,
    "drop": _drop,
    "examine": _examine,
    "inventory": _inventory,
    "save": _save,
    "load": _load,
    "quit": _quit,
    "help": _help,
}
