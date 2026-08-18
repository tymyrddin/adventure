// Shared plumbing for the browser harness: a scratch copy of the sample world, the
// editor serving it, a headless browser, and a DevTools connection to the page.
// Nothing here is imported by the project; see tools/harness/README.md.

import { spawn, spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdtempSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as wait } from "node:timers/promises";
import { fileURLToPath } from "node:url";

export const ROOT = fileURLToPath(new URL("../../", import.meta.url));

const BROWSERS = ["google-chrome", "chromium", "chromium-browser"];

export function scratchWorld() {
  const scratch = mkdtempSync(join(tmpdir(), "cave-harness-"));
  cpSync(join(ROOT, "tests", "worlds", "sample"), join(scratch, "world"),
         { recursive: true });
  return join(scratch, "world");
}

export function freePort() {
  return new Promise((done) => {
    const probe = createServer();
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => done(port));
    });
  });
}

function python() {
  const local = join(ROOT, ".venv", "bin", "python");
  return existsSync(local) ? local : "python3";
}

function browser() {
  const named = process.env.CAVE_BROWSER;
  const found = (named ? [named] : BROWSERS)
    .find((name) => spawnSync("which", [name]).status === 0);
  if (!found) {
    throw new Error(`no browser found; tried ${BROWSERS.join(", ")}. `
      + "Set CAVE_BROWSER to one you have.");
  }
  return found;
}

export async function until(test, complaint, tries = 80) {
  for (let attempt = 0; attempt < tries; attempt += 1) {
    if (await test()) {
      return true;
    }
    await wait(150);
  }
  throw new Error(complaint);
}

export async function startEditor(world, port) {
  const editor = spawn(python(), [
    join(ROOT, "tools", "harness", "serve.py"), world, String(port),
  ], { stdio: "ignore" });
  await until(async () => {
    try {
      return (await fetch(`http://127.0.0.1:${port}/`)).ok;
    } catch (notYet) {
      return false;
    }
  }, "the editor did not start");
  return editor;
}

export async function openPage(url) {
  if (typeof WebSocket === "undefined") {
    throw new Error("this node has no WebSocket; run with --experimental-websocket "
      + "or on node 22 and later");
  }
  const port = await freePort();
  const chrome = spawn(browser(), [
    "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
    `--remote-debugging-port=${port}`, "--window-size=1400,1050", url,
  ], { stdio: "ignore" });
  let socket = null;
  await until(async () => {
    const list = await fetch(`http://127.0.0.1:${port}/json/list`)
      .then((answer) => answer.json())
      .catch(() => []);
    const page = list.find((target) => target.type === "page"
      && target.url.startsWith(url));
    if (!page) {
      return false;
    }
    socket = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((done, fail) => { socket.onopen = done; socket.onerror = fail; });
    return true;
  }, "the browser never showed the page");

  let next = 1;
  const waiting = new Map();
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    const pending = waiting.get(message.id);
    if (pending) {
      waiting.delete(message.id);
      pending(message);
    }
  };

  function call(method, params) {
    const id = next++;
    return new Promise((done) => {
      waiting.set(id, done);
      socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async function evaluate(expression) {
    const answer = await call("Runtime.evaluate", {
      expression, returnByValue: true, awaitPromise: true,
    });
    const blew = answer.result?.exceptionDetails;
    if (blew) {
      throw new Error(blew.exception?.description || blew.text);
    }
    return answer.result?.result?.value;
  }

  await call("Runtime.enable", {});
  await until(async () => {
    try {
      return await evaluate("typeof state !== 'undefined' && Boolean(state.world)");
    } catch (stillLoading) {
      return false;
    }
  }, "the map never loaded");
  return { call, evaluate, close: () => chrome.kill() };
}

export async function harness() {
  const world = scratchWorld();
  const port = await freePort();
  const editor = await startEditor(world, port);
  const url = `http://127.0.0.1:${port}/`;
  const page = await openPage(url);
  return {
    world, url, page,
    stop: () => { page.close(); editor.kill(); },
  };
}
