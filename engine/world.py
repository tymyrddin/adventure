"""Loading, validation and solvability analysis for a world."""

import pathlib
import tomllib

from engine import data


class WorldError(Exception):
    """Raised when a world file fails validation."""


class StateError(Exception):
    """Raised when a saved game cannot be restored."""


_TYPES = {"string": str, "integer": int, "boolean": bool, "array": list, "table": dict}
_ID_TABLES = ("rooms", "things", "actions", "marks")


def load(world):
    """Read the world at this directory, bind its data, validate it, and return it."""
    words = data.load(world)
    path = pathlib.Path(world) / words["builtins"]["files"]["world"]
    words["source"] = str(path)
    try:
        with open(path, "rb") as handle:
            loaded = tomllib.load(handle)
    except OSError as unreadable:
        raise WorldError(str(unreadable)) from unreadable
    except tomllib.TOMLDecodeError as unparsable:
        raise WorldError(str(unparsable)) from unparsable
    errors, _warnings = validate(loaded, words)
    unsaid = [line for line in words["schema"]["said"]
              if line not in _get(words["messages"], "player", {})]
    if unsaid:
        errors.append(_error(words, "unsaid", lines=", ".join(unsaid)))
    if errors:
        raise WorldError("\n".join(errors))
    loaded["words"] = words
    return loaded


def validate(world, words):
    """Return (errors, warnings) as lists of lines."""
    errors = []
    _check_shape(world, words, errors)
    _check_ids(world, words, errors)
    flags = {flag for _id, action in _records(world, "actions")
             for flag in _get(action, "sets", [])}
    flags |= {_get(mark, "sets", "") for _id, mark in _records(world, "marks")} - {""}
    _check_rooms(world, words, flags, errors)
    _check_actions(world, words, errors)
    _check_marks(world, words, errors)
    _check_synonyms(world, words, errors)
    _check_meta(world, words, flags, errors)
    if not errors:
        rooms, _flags, _waves = solvable(world)
        unreachable = sorted(set(_table(world, "rooms")) - rooms)
        if unreachable:
            errors.append(_error(words, "unreachable", rooms=", ".join(unreachable)))
    return errors, _check_warnings(world, words)


def reachable_from(world, origin):
    """Return the set of room ids reachable from origin, ignoring gates."""
    rooms = _table(world, "rooms")
    seen = {origin} if origin in rooms else set()
    queue = list(seen)
    while queue:
        room = rooms.get(queue.pop(0), {})
        exits = _get(room, "exits", {}) if isinstance(room, dict) else {}
        for target in exits.values():
            if target in rooms and target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def solvable(world):
    """Return (rooms, flags, waves): the fixed point and what each iteration opened."""
    rooms, flags, things, waves = set(), set(), set(), []
    start = _get(_table(world, "meta"), "start", "")
    while True:
        was_rooms, was_flags, was_things = set(rooms), set(flags), set(things)
        if start in _table(world, "rooms"):
            rooms.add(start)
        _open_rooms(world, rooms, flags, things)
        _fire_actions(world, rooms, flags, things)
        opened = [room for room, _record in _records(world, "rooms")
                  if room in rooms and room not in was_rooms]
        raised = [flag for flag in _flag_order(world)
                  if flag in flags and flag not in was_flags]
        if opened or raised:
            waves.append({"rooms": opened, "flags": raised})
        elif things == was_things:
            return rooms, flags, waves


def _open_rooms(world, rooms, flags, things):
    """Add the targets of open exits, and the things the known rooms hold."""
    all_rooms = _table(world, "rooms")
    for name, room in _records(world, "rooms"):
        if name not in rooms:
            continue
        things.update(_get(room, "things", []))
        requires = _get(room, "requires", {})
        holding = _get(room, "holding", {})
        for direction, target in _get(room, "exits", {}).items():
            gate = requires.get(direction)
            carried = holding.get(direction)
            if gate is not None and not set(many(gate)) <= flags:
                continue
            if carried is not None and not set(many(carried)) <= things:
                continue
            if target in all_rooms:
                rooms.add(target)


def _fire_actions(world, rooms, flags, things):
    """Add the flags of every action whose room, needs and when conditions are known."""
    for _id, action in _records(world, "actions"):
        in_room = action.get("in_room")
        if in_room is not None and in_room not in rooms:
            continue
        if not set(_get(action, "needs", [])) <= things:
            continue
        if not set(_get(action, "when", [])) <= flags:
            continue
        flags.update(_get(action, "sets", []))


def _flag_order(world):
    """Return every flag any action sets, in file order, without repeats."""
    order = []
    for _id, action in _records(world, "actions"):
        for flag in _get(action, "sets", []):
            if flag not in order:
                order.append(flag)
    return order


def _check_shape(world, words, errors):
    """Report unknown tables, unknown or missing keys, and values of the wrong type."""
    schema = words["schema"]
    for key, value in world.items():
        if key not in schema["top_level"]:
            errors.append(_error(words, "unknown_key", key=key, path="world"))
        elif not isinstance(value, dict):
            errors.append(_error(words, "bad_value", key=key, path="world"))
    if "meta" not in world:
        errors.append(_error(words, "missing_key", key="meta", path="world"))
    else:
        _check_keys(_table(world, "meta"), "meta", schema["meta"], words, errors)
    for table in _ID_TABLES:
        for name, record in _table(world, table).items():
            if isinstance(record, dict):
                _check_keys(record, f"{table}.{name}", schema[table], words, errors)
            else:
                errors.append(_error(words, "bad_value", key=name, path=table))
    for word, target in _table(world, "synonyms").items():
        if not isinstance(target, str):
            errors.append(_error(words, "bad_value", key=word, path="synonyms"))


def _check_ids(world, words, errors):
    """Report room, thing and action ids outside the bare-key charset."""
    charset = frozenset(words["schema"]["id_chars"])
    for table in _ID_TABLES:
        for name in _table(world, table):
            if not name or not set(name) <= charset:
                errors.append(_error(words, "bad_id", id=name, table=table))


def _check_keys(record, path, spec, words, errors):
    """Report unknown, mistyped and missing keys for one record."""
    allowed = dict(spec["required"], **spec["optional"])
    for key, value in record.items():
        if key not in allowed:
            errors.append(_error(words, "unknown_key", key=key, path=path))
        elif not isinstance(value, _TYPES[allowed[key]]):
            errors.append(_error(words, "bad_value", key=key, path=path))
    for key in spec["required"]:
        if key not in record:
            errors.append(_error(words, "missing_key", key=key, path=path))


def _check_rooms(world, words, flags, errors):
    """Report exit, gate, hidden and placement errors for every room."""
    rooms = _table(world, "rooms")
    things = _table(world, "things")
    placed, duplicated = set(), set()
    for name, room in _records(world, "rooms"):
        exits = _get(room, "exits", {})
        for direction, target in exits.items():
            if target not in rooms:
                errors.append(_error(words, "exit_unknown_room",
                                     room=name, dir=direction, target=target))
        for direction, needed in _get(room, "requires", {}).items():
            if direction not in exits:
                errors.append(_error(words, "requires_without_exit", room=name, dir=direction))
            for flag in many(needed):
                if flag not in flags:
                    errors.append(_error(words, "requires_unknown_flag", room=name, flag=flag))
        for direction, held in _get(room, "unless", {}).items():
            if direction not in exits:
                errors.append(_error(words, "unless_without_exit", room=name, dir=direction))
            for flag in many(held):
                if flag not in flags:
                    errors.append(_error(words, "unless_unknown_flag", room=name, flag=flag))
        for direction, needed in _get(room, "holding", {}).items():
            if direction not in exits:
                errors.append(_error(words, "holding_without_exit", room=name, dir=direction))
            for thing in many(needed):
                if thing not in things:
                    errors.append(_error(words, "room_unknown_thing", room=name, thing=thing))
        for direction in _get(room, "hidden", []):
            if direction not in exits:
                errors.append(_error(words, "hidden_without_exit", room=name, dir=direction))
        for thing in _get(room, "things", []):
            if thing not in things:
                errors.append(_error(words, "room_unknown_thing", room=name, thing=thing))
            elif thing in placed and thing not in duplicated:
                duplicated.add(thing)
                errors.append(_error(words, "thing_placed_twice", thing=thing))
            placed.add(thing)


def _check_actions(world, words, errors):
    """Report unknown references, empty sets and duplicate verb-noun pairs."""
    rooms = _table(world, "rooms")
    things = _table(world, "things")
    seen = {}
    for name, action in _records(world, "actions"):
        in_room = action.get("in_room")
        if in_room is not None and in_room not in rooms:
            errors.append(_error(words, "action_unknown_room", id=name, room=in_room))
        noun = _get(action, "noun", "")
        for thing in [noun] + _get(action, "needs", []) + _get(action, "spends", []):
            if thing and thing not in things:
                errors.append(_error(words, "action_unknown_thing", id=name, thing=thing))
        for mark in _get(action, "raises", {}):
            if mark not in _table(world, "marks"):
                errors.append(_error(words, "action_unknown_mark", id=name, mark=mark))
        if "sets" in action and not _get(action, "sets", []):
            errors.append(_error(words, "action_empty_sets", id=name))
        verb = _get(action, "verb", "")
        if (verb, noun) in seen:
            errors.append(_error(words, "duplicate_verb_noun", first=seen[(verb, noun)],
                                 second=name, verb=verb, noun=noun))
        else:
            seen[(verb, noun)] = name


def _check_synonyms(world, words, errors):
    """Report synonym targets that are neither built-in verbs nor action verbs."""
    builtins = words["builtins"]
    known = frozenset(builtins["verbs"]) | frozenset(builtins["abbreviations"])
    verbs = {_get(action, "verb", "") for _id, action in _records(world, "actions")}
    for word, target in _table(world, "synonyms").items():
        if target not in known and target not in verbs:
            errors.append(_error(words, "synonym_unknown_target", word=word, target=target))


def _check_meta(world, words, flags, errors):
    """Report a bad start room, an unreachable ending and an unsupported version."""
    meta = _table(world, "meta")
    start = meta.get("start")
    if "start" in meta and start not in _table(world, "rooms"):
        errors.append(_error(words, "start_missing", id=start))
    ending = meta.get("ending")
    if "ending" in meta and ending not in flags:
        errors.append(_error(words, "ending_unknown_flag", flag=ending))
    version = meta.get("version")
    if "version" in meta and (type(version) is not int or version != 1):
        errors.append(_error(words, "bad_version", version=version))


def _check_marks(world, words, errors):
    """Report a mark whose threshold nothing could ever cross."""
    for name, mark in _records(world, "marks"):
        threshold = mark.get("threshold")
        if isinstance(threshold, int) and not isinstance(threshold, bool) and threshold < 1:
            errors.append(_error(words, "bad_threshold", mark=name, threshold=threshold))


def _check_warnings(world, words):
    """Return warnings for dead ends, unused things and flags nothing requires."""
    warnings = []
    for name, room in _records(world, "rooms"):
        if not _get(room, "exits", {}) and not _get(room, "oneway", False):
            warnings.append(_warning(words, "no_exits", room=name))
    placed = {thing for _id, room in _records(world, "rooms")
              for thing in _get(room, "things", [])}
    needed = {thing for _id, action in _records(world, "actions")
              for thing in _get(action, "needs", [])}
    for thing, _record in _records(world, "things"):
        if thing not in placed and thing not in needed:
            warnings.append(_warning(words, "thing_unused", thing=thing))
    required = {flag for _id, room in _records(world, "rooms")
                for needed in _get(room, "requires", {}).values()
                for flag in many(needed)}
    required |= {flag for _id, action in _records(world, "actions")
                 for flag in _get(action, "when", [])}
    required |= {_get(thing, "light_when", "") for _id, thing in _records(world, "things")}
    required |= {_get(_table(world, "meta"), "ending", "")}
    required |= {flag for _id, room in _records(world, "rooms")
                 for held in _get(room, "unless", {}).values()
                 for flag in many(held)}
    for name, action in _records(world, "actions"):
        for flag in _get(action, "sets", []):
            if flag not in required:
                warnings.append(_warning(words, "flag_unrequired", flag=flag, action=name))
    for name, mark in _records(world, "marks"):
        flag = _get(mark, "sets", "")
        if flag and flag not in required:
            warnings.append(_warning(words, "mark_unrequired", mark=name, flag=flag))
    for name, room in _records(world, "rooms"):
        for direction, held in _get(room, "unless", {}).items():
            for flag in many(held):
                warnings.append(_warning(words, "way_can_shut",
                                         room=name, dir=direction, flag=flag))
    return warnings


def _error(words, name, **fields):
    """Return one error line."""
    return words["reports"]["errors"][name].format(**fields)


def _warning(words, name, **fields):
    """Return one warning line."""
    return words["reports"]["warnings"][name].format(**fields)


def _records(world, table):
    """Return the (id, record) pairs of a top-level table, skipping malformed records."""
    return [(name, record) for name, record in _table(world, table).items()
            if isinstance(record, dict)]


def _table(world, name):
    """Return a top-level table, or an empty one when it is absent or malformed."""
    return _get(world, name, {})


def many(value):
    """Return one condition or a list of them as a list, so callers need not care."""
    return list(value) if isinstance(value, list) else [value]


def _get(record, key, default):
    """Return record[key] when it matches the default's type, otherwise the default."""
    value = record.get(key, default)
    return value if isinstance(value, type(default)) else default
