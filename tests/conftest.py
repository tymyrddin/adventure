"""Lays out a world directory for the tests. The rules are found where they always are."""

import pathlib

import pytest

from engine import data

ROOT = pathlib.Path(__file__).parent.parent
RULES = ROOT / "rules"
WORLDS = pathlib.Path(__file__).parent / "worlds"
SAMPLE = WORLDS / "sample" / "world.toml"


def lay_out(tmp_path, content=None, name="world"):
    """Return a world directory holding content, ready to be loaded."""
    world = tmp_path / name
    world.mkdir(exist_ok=True)
    (world / "world.toml").write_text(
        SAMPLE.read_text() if content is None else content)
    (world / "messages.toml").write_text((SAMPLE.parent / "messages.toml").read_text())
    return world


def broken(tmp_path, name):
    """Return a world directory holding one of the small broken worlds."""
    return lay_out(tmp_path, (WORLDS / name).read_text())


def said(world, name, **fields):
    """Return the line this world would say, so a test pins the choice, not the wording."""
    return world["words"]["messages"]["player"][name].format(**fields)


@pytest.fixture
def world(tmp_path):
    """Return a copy of the sample world as its own directory."""
    return lay_out(tmp_path)


@pytest.fixture
def words(tmp_path):
    """Return the rules a world is bound to, with nothing of its own laid over them."""
    return data.load(lay_out(tmp_path, name="plain"))
