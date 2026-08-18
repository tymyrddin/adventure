"""Serves the editor against one world file, for the browser harness."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from editor.app import create_app  # imported after the path is set

create_app(sys.argv[1]).run(port=int(sys.argv[2]))
