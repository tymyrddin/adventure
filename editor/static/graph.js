"use strict";

// The map. The canvas owns position and selection, the panels own every
// field, and every gesture is one write to the world file, applied whole or refused
// whole. No direction word appears here: the server pairs reverse exits and places new
// rooms, so this file never has to know which way north is.

const FLUSH = 500;

const STYLE = [
  {
    selector: "node",
    style: {
      "label": "data(label)",
      "text-wrap": "wrap",
      "text-valign": "center",
      "background-color": "#e8e4dc",
      "border-width": 1,
      "border-color": "#8a8378",
      "font-size": 11,
      "width": "label",
      "height": "label",
      "padding": "10px",
      "shape": "round-rectangle",
    },
  },
  { selector: "node[?dark]", style: { "background-color": "#c9c3b6" } },
  { selector: "node[?loose]", style: { "border-style": "dashed" } },
  {
    selector: "node[?start]",
    style: { "border-width": 3, "border-color": "#46603c" },
  },
  {
    selector: "node[!reachable], node[?stuck]",
    style: { "background-color": "#f3d8d2", "border-color": "#b4756a" },
  },
  {
    selector: "node:selected",
    style: { "border-width": 3, "border-color": "#2f6ea8" },
  },
  {
    selector: "edge",
    style: {
      "label": "data(label)",
      "curve-style": "bezier",
      "target-arrow-shape": "triangle",
      "line-color": "#8a8378",
      "target-arrow-color": "#8a8378",
      "source-arrow-color": "#8a8378",
      "font-size": 10,
      "text-background-color": "#fdfcfa",
      "text-background-opacity": 1,
      "width": 1.5,
    },
  },
  { selector: "edge[?both]", style: { "source-arrow-shape": "triangle" } },
  { selector: "edge[?gate]", style: { "line-style": "dashed" } },
  { selector: "edge[?hidden]", style: { "line-style": "dotted" } },
  {
    selector: "edge[?goes]",
    style: {
      "line-color": "#b4756a",
      "target-arrow-color": "#b4756a",
      "line-style": "dashed",
      "curve-style": "unbundled-bezier",
      "control-point-distances": [40],
      "control-point-weights": [0.5],
      "font-style": "italic",
      "color": "#8a5a4f",
    },
  },
];

const state = {
  world: null,
  mtime: 0,
  graph: null,
  room: null,
  exit: null,
  action: null,
  thing: null,
  placeHere: false,
  made: null,
  view: "room",
};

const moved = new Map();
let cy = null;
let pending = null;

// Reading.

async function load() {
  const response = await fetch("/api/world");
  if (!response.ok) {
    element("graph").textContent = "No map: the world file will not parse.";
    element("panel").innerHTML = "";
    await check();
    return;
  }
  const body = await response.json();
  state.world = body.world;
  state.mtime = body.mtime;
  state.graph = await (await fetch("/api/graph")).json();
  if (!table("rooms")[state.room]) {
    state.room = null;
  }
  drawMap();
  drawPanel();
  await check();
}

function table(name) {
  return (state.world && state.world[name]) || {};
}

// The canvas.

function drawMap() {
  const camera = cy ? { pan: cy.pan(), zoom: cy.zoom() } : null;
  if (cy) {
    cy.destroy();
  }
  cy = cytoscape({
    container: element("graph"),
    elements: elements(state.graph),
    style: STYLE,
    layout: { name: "preset" },
    wheelSensitivity: 0.2,
  });
  if (camera) {
    cy.zoom(camera.zoom);
    cy.pan(camera.pan);
  } else {
    cy.fit(undefined, 40);
  }
  if (state.room) {
    cy.$id(state.room).select();
  }
  cy.on("tap", "node", (event) => pick(event.target.id(), null));
  cy.on("tap", "edge", (event) => {
    const edge = event.target;
    if (edge.data("goes")) {
      pickAction(edge.data("source"), edge.data("action"));
    } else {
      pick(edge.data("source"), edge.data("dir"));
    }
  });
  cy.on("dragfree", "node", (event) => remember(event.target));
}

function elements(graph) {
  const nodes = graph.nodes.map((node) => ({
    data: {
      id: node.id,
      label: node.name,
      reachable: node.reachable,
      stuck: node.wave === null,
      dark: node.dark,
      start: node.start,
      loose: !node.placed,
    },
    position: { x: node.x, y: node.y },
  }));
  const drawn = new Map();
  const edges = [];
  graph.edges.forEach((edge, index) => {
    const twin = edge.pair ? drawn.get(edge.pair) : null;
    if (twin) {
      twin.data.label = `${twin.data.dir} / ${edge.dir}`;
      twin.data.both = true;
      return;
    }
    const said = [].concat(edge.gate || []).map((flag) => flag.replace(/_/g, " "))
      .concat([].concat(edge.holds || [])
        .map((id) => `have ${called("things", id)}`))
      .concat([].concat(edge.shuts || [])
        .map((flag) => `shuts on ${flag.replace(/_/g, " ")}`));
    const drawing = {
      data: {
        id: `e${index}`,
        source: edge.from,
        target: edge.to,
        dir: edge.dir,
        label: said.length ? `${edge.dir} · ${said.join(", ")}` : edge.dir,
        gate: said.length > 0,
        hidden: edge.hidden,
        both: false,
      },
    };
    if (edge.pair) {
      drawn.set(edge.pair, drawing);
    }
    edges.push(drawing);
  });
  (graph.goes || []).forEach((move, index) => {
    if (!move.from) {
      return;
    }
    edges.push({
      data: {
        id: `g${index}`,
        source: move.from,
        target: move.to,
        dir: move.verb,
        label: move.verb,
        action: move.action,
        goes: true,
        both: false,
      },
    });
  });
  return nodes.concat(edges);
}

function pick(room, direction) {
  state.room = room;
  state.exit = direction;
  state.action = null;
  state.thing = null;
  state.view = "room";
  cy.$("node:selected").unselect();
  cy.$id(room).select();
  drawPanel();
}

function pickAction(room, action) {
  state.room = room;
  state.exit = null;
  state.action = action;
  state.thing = null;
  state.view = "room";
  cy.$("node:selected").unselect();
  cy.$id(room).select();
  drawPanel();
}

// Dragging.

function remember(node) {
  const at = node.position();
  moved.set(node.id(), { x: at.x, y: at.y });
  clearTimeout(pending);
  pending = setTimeout(writeLayout, FLUSH);
}

async function writeLayout() {
  if (moved.size === 0) {
    return;
  }
  const positions = Object.fromEntries(moved);
  moved.clear();
  if (await keepRoom()) {
    await send("PUT", "/api/layout", { positions });
  }
}

// Writing.

async function send(method, route, body) {
  const response = await fetch(route, {
    method: method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({ mtime: state.mtime }, body)),
  });
  const answer = await response.json().catch(() => ({ errors: ["No answer."] }));
  if (response.ok) {
    notice("");
    state.mtime = answer.mtime;
    state.made = answer.id || null;
    await load();
    return true;
  }
  notice((answer.errors || ["Refused."]).join(" "));
  const fresh = await fetch("/api/world");
  if (fresh.ok && (await fresh.json()).mtime !== state.mtime) {
    await load();
  }
  return false;
}

function notice(message) {
  element("notice").textContent = message;
}

// The panels.

function drawPanel() {
  const panel = element("panel");
  panel.innerHTML = flags() + (state.view === "world" ? worldPanel() : roomPanel());
  const row = panel.querySelector(`[data-exit="${cssEscape(state.exit)}"]`);
  if (row) {
    row.classList.add("chosen");
  }
}

function cssEscape(text) {
  return String(text === null ? "" : text).replace(/["\\]/g, "\\$&");
}

function flagNames() {
  const known = [];
  Object.values(table("actions")).forEach((action) =>
    (action.sets || []).forEach((flag) => {
      if (!known.includes(flag)) {
        known.push(flag);
      }
    }));
  return known;
}

function carriable(also) {
  const held = [].concat(also || []);
  return Object.keys(table("things"))
    .filter((id) => table("things")[id].portable || held.includes(id));
}

function conditions(holds) {
  const list = carriable(holds).map((id) => ({
    key: `have:${id}`, label: `have ${called("things", id)}`,
  }));
  flagNames().forEach((flag) => list.push({
    key: `after:${flag}`, label: flag.replace(/_/g, " "),
  }));
  return list;
}

function conditionBoxes(gate, holds) {
  const list = conditions(holds);
  if (list.length === 0) {
    return '<span class="empty">Nothing to wait for yet.</span>';
  }
  const on = [].concat(holds || []).map((id) => `have:${id}`)
    .concat([].concat(gate || []).map((flag) => `after:${flag}`));
  return `<div class="ticks">${list.map((one) => `
    <label class="tick"><input type="checkbox" data-cond value="${escape(one.key)}"${
      on.includes(one.key) ? " checked" : ""}> ${escape(one.label)}</label>`).join("")}</div>`;
}


function shutBoxes(unless) {
  const names = flagNames();
  if (names.length === 0) {
    return '<span class="empty">Nothing can shut it yet.</span>';
  }
  const on = [].concat(unless || []);
  return `<div class="ticks">${names.map((flag) => `
    <label class="tick"><input type="checkbox" data-shut value="${escape(flag)}"${
      on.includes(flag) ? " checked" : ""}> ${escape(flag.replace(/_/g, " "))}</label>`)
    .join("")}</div>`;
}


function flags() {
  const options = flagNames().map((flag) => `<option value="${escape(flag)}">`);
  return `<datalist id="flags">${options.join("")}</datalist>`;
}

function roomPanel() {
  if (!state.room) {
    return '<p class="empty">Tap a room to edit it.</p>';
  }
  const id = state.room;
  const room = table("rooms")[id];
  const start = (state.world.meta || {}).start === id;
  return `
    <h2>${escape(room.name || id)}${start ? ' <em>start</em>' : ""}</h2>
    <div data-form="room">
      ${row("Name", text("name", room.name))}
      ${row("Description", area("desc", room.desc))}
      ${row("Dark inside", tick("dark", room.dark))}
      ${row("Dead end on purpose", tick("oneway", room.oneway))}
      <h3>Exits</h3>
      <div data-exits>${exitRows(room)}</div>
      <button type="button" data-do="add-exit">Add exit</button>
      <h3>Things here</h3>
      ${thingBoxes(room)}
      ${state.thing === null
        ? '<button type="button" data-do="new-thing-here">New thing here</button>' : ""}
    </div>
    ${state.thing === null ? "" : thingForm(state.thing)}
    <div class="record" data-form="new">
      <p class="what">A new room from here</p>
      ${row("Direction", text("dir", ""))}
      ${row("Name", text("newname", ""))}
      ${row("Open only when", conditionBoxes("", ""))}
      ${row("Both ways", tick("reverse", true))}
      <div class="buttons">
        <button type="button" data-do="make-room">Save</button>
      </div>
    </div>
    <h3>What can be done here</h3>
    ${actionList((action) => action.in_room === id)}
    <div class="dock">
      <button type="button" data-do="save-room">Save room</button>
      <button type="button" data-do="delete-room" class="danger">Delete room</button>
    </div>
  `;
}

function worldPanel() {
  const meta = state.world.meta || {};
  return `
    <h2>World</h2>
    <div data-form="meta">
      ${row("Title", text("title", meta.title))}
      ${row("Start room", choose("start", Object.keys(table("rooms")), meta.start, undefined, "rooms"))}
      ${row("Ends when", choose("ending", flagNames(), meta.ending, "(never ends)"))}
      <button type="button" data-do="save-meta">Save world</button>
    </div>
    <h3>Things</h3>
    ${thingList()}
    <h3>What can be done anywhere</h3>
    ${actionList((action) => action.in_room === undefined)}
    <h3>Footprints a move can leave</h3>
    <p class="hint">A named cost that builds up. When it reaches its mark, the world
      remembers a flag — which a way can then shut on, or the game can end on.</p>
    ${marksSection()}
  `;
}

function marksSection() {
  const marks = table("marks");
  const rows = Object.keys(marks).map((name) => markRow(name, marks[name])).join("");
  return `
    <div data-form="marks">
      ${rows || '<p class="empty">No footprints yet.</p>'}
      <button type="button" data-do="add-mark">Add footprint</button>
      <button type="button" data-do="save-marks">Save footprints</button>
    </div>`;
}

function markRow(name, mark) {
  return `
    <div class="mark" data-mark>
      <input type="text" data-field="name" size="10" value="${escape(name)}"
             placeholder="its name">
      <span class="tag">reaches</span>
      <input type="number" data-field="threshold" min="1" size="3"
             value="${escape(mark.threshold === undefined ? "" : mark.threshold)}">
      <span class="tag">then remembers</span>
      <input type="text" data-field="sets" list="flags" size="12"
             value="${escape(mark.sets || "")}" placeholder="a flag">
      <button type="button" data-do="drop-mark">×</button>
    </div>`;
}

function marksRecord() {
  const marks = {};
  form("marks").querySelectorAll("[data-mark]").forEach((row) => {
    const name = value(row, "name");
    const threshold = parseInt(value(row, "threshold"), 10);
    const sets = value(row, "sets");
    if (name) {
      marks[name] = { threshold: Number.isNaN(threshold) ? 0 : threshold, sets: sets };
    }
  });
  return marks;
}

function exitRows(room) {
  const exits = room.exits || {};
  const requires = room.requires || {};
  const holding = room.holding || {};
  const hidden = room.hidden || [];
  const rooms = Object.keys(table("rooms"));
  return Object.keys(exits).map((direction) => `
    <div class="exit" data-exit="${escape(direction)}">
      <input type="text" data-field="dir" size="7" value="${escape(direction)}">
      <span class="tag">to</span>
      ${choose("to", rooms, exits[direction], undefined, "rooms")}
      <button type="button" data-do="drop-exit">×</button>
      <span class="tag">open only when</span>
      ${conditionBoxes(requires[direction], holding[direction])}
      <span class="tag">shuts once</span>
      ${shutBoxes((room.unless || {})[direction])}
      <label><input type="checkbox" data-field="hidden"${
        hidden.includes(direction) ? " checked" : ""}> hidden until it opens</label>
    </div>`).join("") || '<p class="empty">No exits.</p>';
}

function thingBoxes(room) {
  const here = room.things || [];
  const placed = new Set();
  Object.values(table("rooms")).forEach((other) =>
    (other.things || []).forEach((thing) => placed.add(thing)));
  const free = Object.keys(table("things"))
    .filter((thing) => here.includes(thing) || !placed.has(thing));
  if (free.length === 0) {
    return '<p class="empty">Every thing is placed elsewhere.</p>';
  }
  return free.map((thing) => `
    <div class="tickrow">
      <label class="tick">
        <input type="checkbox" data-thing value="${escape(thing)}"${
          here.includes(thing) ? " checked" : ""}>
        ${escape(table("things")[thing].name || thing)}
      </label>
      <button type="button" data-do="edit-thing" data-id="${escape(thing)}">Edit</button>
    </div>`).join("");
}

function thingList() {
  const things = Object.keys(table("things"));
  const rows = things.map((id) => state.thing === id ? thingForm(id) : `
    <p class="record">
      ${escape(table("things")[id].name || id)}
      <button type="button" data-do="edit-thing" data-id="${escape(id)}">Edit</button>
    </p>`).join("");
  const maker = state.thing === ""
    ? thingForm("")
    : '<button type="button" data-do="new-thing">New thing</button>';
  return (rows || '<p class="empty">No things.</p>') + maker;
}




function nameTaken(kind, name, self) {
  return Object.keys(table(`${kind}s`)).some((id) =>
    id !== self && (table(`${kind}s`)[id].name || "") === name);
}



function thingForm(id) {
  const thing = table("things")[id] || {};
  return `
    <div class="record" data-form="thing" data-id="${escape(id)}">
      <p class="what">${id ? "This thing" : "A new thing"}</p>
      ${row("Name", text("name", thing.name))}
      ${row("Description", area("desc", thing.desc))}
      ${row("Can be carried", tick("portable", thing.portable))}
      ${id ? row("Gives light", `<input type="checkbox" data-do="lighting"${
        thing.light_when ? " checked" : ""}>`) : ""}
      ${id ? `<div class="row${thing.light_when ? "" : " away"}" data-lightrow>
        <span>…while flag</span>${
          text("light_when", thing.light_when, "flags", "a flag name")}</div>` : ""}
      <div class="buttons">
        <button type="button" data-do="save-thing">Save</button>
        ${id ? '<button type="button" data-do="delete-thing" class="danger">Delete</button>'
             : ""}
        <button type="button" data-do="close-record">Close</button>
      </div>
    </div>`;
}

function actionList(wanted) {
  const ids = Object.keys(table("actions")).filter((id) => wanted(table("actions")[id]));
  const rows = ids.map((id) => state.action === id ? actionForm(id) : `
    <p class="record">
      ${escape(table("actions")[id].verb || "")}
      ${escape(table("actions")[id].noun || "")}
      <button type="button" data-do="edit-action" data-id="${escape(id)}">Edit</button>
    </p>`).join("");
  const maker = state.action === ""
    ? actionForm("")
    : '<button type="button" data-do="new-action">New action</button>';
  return (rows || '<p class="empty">None.</p>') + maker;
}

function actionForm(id) {
  const here = state.view === "room" && state.room ? { in_room: state.room } : {};
  const action = table("actions")[id] || here;
  const things = Object.keys(table("things"));
  const conditioned = (made, record) => Boolean(made)
    && (record.in_room !== undefined || (record.needs || []).length
        || (record.when || []).length || record.once === false
        || (record.spends || []).length || record.goes !== undefined
        || Object.keys(record.raises || {}).length);
  return `
    <div class="record" data-form="action" data-id="${escape(id)}">
      <p class="what">${id ? "This action" : "A new action"}</p>
      <p class="hint">A verb your world adds, such as dig or light. Moving, taking and
        looking are already built in.</p>
      ${row("The player types", text("verb", action.verb, null, "a verb, such as dig"))}
      ${row("…on this thing", choose("noun", things, action.noun, undefined, "things"))}
      ${row("Say to the player", area("message", action.message))}
      <button type="button" data-do="conditions">Only sometimes…</button>
      <div data-more class="${conditioned(id, action) ? "" : "away"}">
        ${row("Only in", choose("in_room", Object.keys(table("rooms")),
                            action.in_room, "anywhere", "rooms"))}
        ${row("Only while carrying", boxes(carriable(action.needs), action.needs || []))}
        ${row("Only after", text("when", (action.when || []).join(", "),
                                 "flags", "nothing needs to have happened"))}
        ${row("Works only once", tick("once", action.once !== false))}
        ${row("Remembered as", text("sets", (action.sets || []).join(", "),
                                    "flags", "named after the action itself"))}
        ${row("Uses up", spendBoxes(action.spends || []))}
        ${row("Then sends you to", choose("goes", Object.keys(table("rooms")),
                            action.goes, "nowhere, you stay put", "rooms"))}
        ${raisesRows(action.raises || {})}
      </div>
      <div class="buttons">
        <button type="button" data-do="save-action">Save</button>
        ${id ? '<button type="button" data-do="delete-action" class="danger">Delete</button>'
             : ""}
        <button type="button" data-do="close-record">Close</button>
      </div>
    </div>`;
}

// Controls.

function row(label, control) {
  return `<div class="row"><span>${escape(label)}</span>${control}</div>`;
}

function text(name, value, list, hint) {
  return `<input type="text" data-field="${name}" value="${escape(value || "")}"${
    list ? ` list="${list}"` : ""}${hint ? ` placeholder="${escape(hint)}"` : ""}>`;
}

function area(name, value) {
  return `<textarea data-field="${name}" rows="3">${escape(value || "")}</textarea>`;
}

function tick(name, on) {
  return `<input type="checkbox" data-field="${name}"${on ? " checked" : ""}>`;
}

function choose(name, options, value, blank, kind) {
  const empty = blank === undefined
    ? []
    : [`<option value=""${value === undefined ? " selected" : ""}>${escape(blank)}</option>`];
  const items = options.map((id) =>
    `<option value="${escape(id)}"${id === value ? " selected" : ""}>${
      escape(called(kind, id))}</option>`);
  return `<select data-field="${name}">${empty.concat(items).join("")}</select>`;
}

function called(kind, id) {
  return kind ? ((table(kind)[id] || {}).name || id) : id;
}

function boxes(options, chosen) {
  if (options.length === 0) {
    return '<span class="empty">None.</span>';
  }
  return `<div class="ticks">${options.map((id) => `
    <label class="tick"><input type="checkbox" data-box value="${escape(id)}"${
      chosen.includes(id) ? " checked" : ""}> ${
      escape((table("things")[id] || {}).name || id)}</label>`).join("")}</div>`;
}

function spendBoxes(chosen) {
  const things = Object.keys(table("things"));
  if (things.length === 0) {
    return '<span class="empty">Nothing to use up.</span>';
  }
  return `<div class="ticks">${things.map((id) => `
    <label class="tick"><input type="checkbox" data-spend value="${escape(id)}"${
      chosen.includes(id) ? " checked" : ""}> ${
      escape((table("things")[id] || {}).name || id)}</label>`).join("")}</div>`;
}

function raisesRows(raises) {
  const marks = Object.keys(table("marks"));
  if (marks.length === 0) {
    return `<div class="row"><span>Leaves a footprint</span>` +
      `<span class="empty">Make a footprint in the world panel first.</span></div>`;
  }
  return marks.map((name) => `<div class="row" data-raise-row>
    <span>Adds to ${escape(name)}</span>
    <input type="number" data-raise="${escape(name)}" min="0" size="3"
           value="${escape(raises[name] || 0)}"></div>`).join("");
}

function escape(raw) {
  return String(raw === null || raw === undefined ? "" : raw).replace(
    /[&<>"']/g,
    (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
}

// Reading a form back.

function form(name) {
  return element("panel").querySelector(`[data-form="${name}"]`);
}

function value(scope, name) {
  const field = scope.querySelector(`[data-field="${name}"]`);
  return field ? field.value.trim() : "";
}

function checked(scope, name) {
  const field = scope.querySelector(`[data-field="${name}"]`);
  return Boolean(field && field.checked);
}

function list(written) {
  return written.split(",").map((item) => item.trim()).filter(Boolean);
}

function roomRecord() {
  const scope = form("room");
  const record = { name: value(scope, "name"), desc: value(scope, "desc") };
  const exits = {};
  const requires = {};
  const holding = {};
  const unless = {};
  const hidden = [];
  scope.querySelectorAll("[data-exit]").forEach((line) => {
    const direction = value(line, "dir");
    if (!direction) {
      return;
    }
    exits[direction] = value(line, "to");
    const ticked = [...line.querySelectorAll("[data-cond]:checked")].map((box) => box.value);
    const after = ticked.filter((key) => key.startsWith("after:"))
      .map((key) => key.slice(6));
    const held = ticked.filter((key) => key.startsWith("have:")).map((key) => key.slice(5));
    if (after.length) {
      requires[direction] = after;
    }
    if (held.length) {
      holding[direction] = held;
    }
    const shut = [...line.querySelectorAll("[data-shut]:checked")].map((box) => box.value);
    if (shut.length) {
      unless[direction] = shut;
    }
    if (checked(line, "hidden")) {
      hidden.push(direction);
    }
  });
  const things = [...scope.querySelectorAll("[data-thing]:checked")]
    .map((box) => box.value);
  return trim(Object.assign(record, {
    exits: exits, requires: requires, holding: holding, unless: unless,
    hidden: hidden, things: things,
    dark: checked(scope, "dark"), oneway: checked(scope, "oneway"),
  }));
}

function thingRecord(scope) {
  return trim({
    name: value(scope, "name"),
    desc: value(scope, "desc"),
    portable: checked(scope, "portable"),
    light_when: value(scope, "light_when"),
  });
}

function actionRecord(scope) {
  const record = {
    verb: value(scope, "verb"),
    noun: value(scope, "noun"),
    needs: [...scope.querySelectorAll("[data-box]:checked")].map((box) => box.value),
    when: list(value(scope, "when")),
    sets: list(value(scope, "sets")),
    message: value(scope, "message"),
  };
  if (value(scope, "in_room")) {
    record.in_room = value(scope, "in_room");
  }
  if (value(scope, "goes")) {
    record.goes = value(scope, "goes");
  }
  if (!checked(scope, "once")) {
    record.once = false;
  }
  const spends = [...scope.querySelectorAll("[data-spend]:checked")].map((box) => box.value);
  if (spends.length) {
    record.spends = spends;
  }
  const raises = {};
  scope.querySelectorAll("[data-raise]").forEach((input) => {
    const amount = parseInt(input.value, 10);
    if (amount > 0) {
      raises[input.getAttribute("data-raise")] = amount;
    }
  });
  if (Object.keys(raises).length) {
    record.raises = raises;
  }
  return trim(record, ["sets"]);
}

function trim(record, keep) {
  const kept = {};
  Object.keys(record).forEach((key) => {
    const held = record[key];
    const empty = held === "" || held === false
      || (Array.isArray(held) && held.length === 0)
      || (held && typeof held === "object" && !Array.isArray(held)
          && Object.keys(held).length === 0);
    if (!empty || (keep || []).includes(key)) {
      kept[key] = held;
    }
  });
  return kept;
}

// What the buttons do.

const JOBS = {
  "add-exit": () => {
    const rooms = Object.keys(table("rooms"));
    const empty = element("panel").querySelector('[data-exits] .empty');
    if (empty) {
      empty.remove();
    }
    element("panel").querySelector("[data-exits]").insertAdjacentHTML("beforeend", `
      <div class="exit" data-exit="">
        <input type="text" data-field="dir" size="7" value="">
        <span class="tag">to</span>
        ${choose("to", rooms, state.room, undefined, "rooms")}
        <button type="button" data-do="drop-exit">×</button>
        <span class="tag">open only when</span>
        ${conditionBoxes("", "")}
        <label><input type="checkbox" data-field="hidden"> not listed</label>
      </div>`);
  },
  "drop-exit": (button) => {
    button.closest("[data-exit]").remove();
    return keepRoom();
  },
  "save-room": () => keepRoom(),
  "delete-room": () => send("DELETE", `/api/rooms/${state.room}`, {}),
  "make-room": async () => {
    const scope = form("new");
    const direction = value(scope, "dir");
    const name = value(scope, "newname");
    const reverse = checked(scope, "reverse");
    const ticked = [...scope.querySelectorAll("[data-cond]:checked")].map((box) => box.value);
    const gate = ticked.filter((key) => key.startsWith("after:")).map((key) => key.slice(6));
    const holds = ticked.filter((key) => key.startsWith("have:")).map((key) => key.slice(5));
    const source = state.room;
    if (!direction) {
      notice("Which direction from here?");
      return false;
    }
    if (nameTaken("room", name, null)) {
      notice("Another room is already called that.");
      return false;
    }
    if (!await keepRoom()) {
      return false;
    }
    return send("POST", "/api/rooms", {
      room: { name: name, desc: "" },
      from: { room: source, dir: direction, reverse: reverse, gate: gate, holds: holds },
    });
  },
  "save-meta": () => {
    const scope = form("meta");
    return send("PUT", "/api/meta", {
      meta: { title: value(scope, "title"), start: value(scope, "start"),
              ending: value(scope, "ending") },
    });
  },
  "add-mark": () => {
    const empty = form("marks").querySelector(".empty");
    if (empty) {
      empty.remove();
    }
    form("marks").querySelector('[data-do="add-mark"]')
      .insertAdjacentHTML("beforebegin", markRow("", {}));
  },
  "drop-mark": (button) => {
    button.closest("[data-mark]").remove();
  },
  "save-marks": () => send("PUT", "/api/marks", { marks: marksRecord() }),
  "conditions": (button) => {
    button.closest("[data-form]").querySelector("[data-more]").classList.toggle("away");
  },
  "lighting": (box) => {
    const line = form("thing").querySelector("[data-lightrow]");
    line.classList.toggle("away", !box.checked);
    if (!box.checked) {
      line.querySelector('[data-field="light_when"]').value = "";
    }
  },
  "new-thing": async () => { await keepRoom(); state.thing = ""; state.placeHere = false; drawPanel(); },
  "new-thing-here": async () => { await keepRoom(); state.thing = ""; state.placeHere = true; drawPanel(); },
  "edit-thing": async (button) => { const id = button.dataset.id; await keepRoom(); state.thing = id; drawPanel(); },
  "save-thing": async () => {
    const scope = form("thing");
    const id = scope.dataset.id;
    const record = thingRecord(scope);
    const here = state.placeHere && state.room;
    if (nameTaken("thing", record.name || "", id || null)) {
      notice("Another thing is already called that.");
      return false;
    }
    if (!await keepRoom()) {
      return false;
    }
    if (id) {
      return send("PUT", `/api/things/${id}`, { thing: record });
    }
    if (!await send("POST", "/api/things", { thing: record })) {
      return false;
    }
    if (here) {
      await placeInRoom(state.made);
    }
    return close();
  },
  "delete-thing": async () => {
    const id = form("thing").dataset.id;
    return await keepRoom() && send("DELETE", `/api/things/${id}`, {});
  },
  "new-action": async () => { await keepRoom(); state.action = ""; drawPanel(); },
  "edit-action": async (button) => { const id = button.dataset.id; await keepRoom(); state.action = id; drawPanel(); },
  "save-action": async () => {
    const scope = form("action");
    const id = scope.dataset.id;
    const record = actionRecord(scope);
    if (!await keepRoom()) {
      return false;
    }
    if (id) {
      return send("PUT", `/api/actions/${id}`, { action: record });
    }
    return await send("POST", "/api/actions", { action: record }) && close();
  },
  "delete-action": async () => {
    const id = form("action").dataset.id;
    return await keepRoom() && send("DELETE", `/api/actions/${id}`, {});
  },
  "close-record": () => close(),
};

// Any write from a room panel reloads it from disk, so whatever the author has typed
// into the room and not yet saved goes first, or it would be thrown away unasked.
async function keepRoom() {
  if (state.view !== "room" || !state.room || !form("room")) {
    return true;
  }
  const typed = roomRecord();
  if (JSON.stringify(typed) === JSON.stringify(savedRoom())) {
    return true;
  }
  if (nameTaken("room", typed.name || "", state.room)) {
    notice("Another room is already called that.");
    return false;
  }
  return send("PUT", `/api/rooms/${state.room}`, { room: typed });
}

function savedRoom() {
  const saved = table("rooms")[state.room] || {};
  return trim({
    name: saved.name || "",
    desc: saved.desc || "",
    exits: saved.exits || {},
    requires: saved.requires || {},
    holding: saved.holding || {},
    unless: saved.unless || {},
    hidden: saved.hidden || [],
    things: saved.things || [],
    dark: Boolean(saved.dark),
    oneway: Boolean(saved.oneway),
  });
}

async function placeInRoom(thing) {
  const room = table("rooms")[state.room];
  if (!room) {
    return;
  }
  await send("PUT", `/api/rooms/${state.room}`, {
    room: Object.assign({}, room, { things: (room.things || []).concat([thing]) }),
  });
}

function close() {
  state.action = null;
  state.thing = null;
  state.placeHere = false;
  drawPanel();
  return true;
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-do]");
  if (button) {
    await JOBS[button.dataset.do](button);
    return;
  }
  if (event.target.id === "show-world") {
    state.view = state.view === "world" ? "room" : "world";
    drawPanel();
  }
});

// The validation strip.

async function check() {
  const report = await (await fetch("/api/validate", { method: "POST" })).json();
  const clean = report.errors.length === 0 && report.warnings.length === 0;
  element("report").innerHTML =
    (clean ? '<p class="clean">No errors, no warnings.</p>' : "")
    + lines("Errors", report.errors, "errors")
    + lines("Warnings", report.warnings, "warnings")
    + waves(report.waves);
}

function lines(title, said, kind) {
  if (said.length === 0) {
    return "";
  }
  const items = said.map((line) => `<li>${escape(line)}</li>`).join("");
  return `<h3 class="${kind}">${title}</h3><ul class="${kind}">${items}</ul>`;
}

function waves(said) {
  const rows = said.filter((wave) => wave.rooms.length)
    .map((wave) => `<li>${escape(wave.rooms.map((id) => called("rooms", id)).join(", "))}</li>`);
  return rows.length ? `<h3>Opens in this order</h3><ol>${rows.join("")}</ol>` : "";
}

function element(id) {
  return document.getElementById(id);
}

load();
