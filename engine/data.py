"""Reads the system's own tables, with a world's own laid over them."""

import pathlib
import tomllib

RULES = pathlib.Path(__file__).resolve().parents[1] / "rules"
SHARED = ("builtins", "reports", "schema")
OWN = ("messages",)


def load(world):
    """Return the shared tables with this world's laid over them, and its own words."""
    here = pathlib.Path(world)
    words = {name: _over(read(RULES, name), read(here, name)) for name in SHARED}
    return words | {name: read(here, name) for name in OWN}


def read(directory, name):
    """Return one data file from a directory, or an empty table when it has none."""
    path = pathlib.Path(directory) / f"{name}.toml"
    if not path.is_file():
        return {}
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def _over(base, own):
    """Return the rules with the world's own tables merged into them, one level deep."""
    merged = dict(base)
    for key, value in own.items():
        merged[key] = (dict(merged[key], **value)
                       if isinstance(value, dict) and isinstance(merged.get(key), dict)
                       else value)
    return merged
