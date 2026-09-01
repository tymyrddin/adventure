import pathlib
import tomllib

RULES = pathlib.Path(__file__).resolve().parents[1] / "rules"
SHARED = ("builtins", "reports", "schema")
OWN = ("messages",)


def load(world):
    here = pathlib.Path(world)
    words = {name: _over(read(RULES, name), read(here, name)) for name in SHARED}
    return words | {name: read(here, name) for name in OWN}


def read(directory, name):
    """Return one data file from a directory, or an empty table when it has none."""
    path = pathlib.Path(directory) / f"{name}.toml"
    if not path.is_file():
        return {}
    with open(path, "rb") as handle:
        try:
            return tomllib.load(handle)
        except tomllib.TOMLDecodeError as unparsable:
            raise tomllib.TOMLDecodeError(f"{path}: {unparsable}") from unparsable


def _over(base, own):
    """Merge, one level deep. Deeper than that nobody has needed."""
    merged = dict(base)
    for key, value in own.items():
        merged[key] = (dict(merged[key], **value)
                       if isinstance(value, dict) and isinstance(merged.get(key), dict)
                       else value)
    return merged
