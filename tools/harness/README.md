# Browser harness

The by-hand check of the map, written down so it can be repeated. The drawing has no
pytest coverage, because no JS test runner is a dependency of this project; this runs
the real page in a real browser instead, and asks it questions.

It is a development tool and not part of the project. Nothing under `engine/`, `cli/`
or `editor/` imports it, pytest does not collect it, and neither the game nor the
editor needs it to run.

## Running it

```
node --experimental-websocket tools/harness/check.mjs
```

Node 22 and later have `WebSocket` already, so the flag can go. It starts the editor
on a free port against a throwaway copy of `content/world.toml`, drives the page, and
exits non-zero if any check fails. Your own world file is never touched.

A screenshot, for looking at rather than asserting on:

```
node --experimental-websocket tools/harness/shot.mjs map.png
node --experimental-websocket tools/harness/shot.mjs panel.png "cy.\$id('grotto').emit('tap')"
```

## What it needs

Node, and one of `google-chrome`, `chromium` or `chromium-browser` on the path. Set
`CAVE_BROWSER` to name a different one. Neither is a project dependency: if you do not
have them, the harness does not run and nothing else is affected.

## How it reaches the page

`graph.js` is a plain script, so its top-level `const` and `let` bindings live in the
page's global scope. The harness evaluates expressions against them over the DevTools
protocol: `cy` is the cytoscape instance, `state` is what the page believes, `JOBS`
holds what the buttons do. So a check like `JOBS['save-room']()` runs the same code
path a click runs, rather than a reimplementation of it.
