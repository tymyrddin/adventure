# Contributing

## Setup

The project uses Python 3.12. The engine and CLI use only the standard library; the editor
adds Flask and tomlkit.

```text
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## The checks

CI runs three checks on every push and pull request:

```text
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy
```

The editor's JavaScript is covered by a small pure-Python lint inside the pytest run, so
there is no npm toolchain. To run ruff and mypy before each commit, install the pre-commit
hooks:

```text
.venv/bin/pre-commit install
```

## Code and worlds

The engine, CLI and editor are code: the tests record the intended behaviour, so change them
alongside any behaviour you change.

The worlds in `content/` are prose. Room and thing descriptions can be rewritten freely, but
a line in a `messages.toml` table is asserted in the tests, so rewording it means updating
those assertions. The worlds after the cave put the player in an attacker's decisions on a
terrain, showing reasoning and consequence rather than teaching technique.

## The golden transcript

One test plays a whole game and checks the output byte for byte, and it is not regenerated
automatically. If you change the sample world under `tests/worlds/sample/`, regenerate the
record and read the diff:

```text
python -m cli.play tests/worlds/sample --script tests/golden/walkthrough.script \
    --transcript tests/golden/walkthrough.transcript
```

Delete the old transcript first, since `--transcript` appends.

## The browser harness

The editor's JavaScript is exercised by a harness under `tools/harness/` that drives the page
in a real browser. It needs Node and a browser and is not part of pytest or CI, so run it by
hand when you touch the editor front end:

```text
node --experimental-websocket tools/harness/check.mjs
```

## Conduct and reporting

Taking part here means keeping to the [code of conduct](CODE_OF_CONDUCT.md). If you find a
security problem in the engine or the editor, do not open a public issue; the
[security policy](SECURITY.md) explains how to report it privately.

## Licensing

The engine and tooling are under the MIT Licence (`LICENCE`). The authored worlds under
`content/` are under Creative Commons Attribution 4.0 (`content/LICENCE`).
