// Drives the editor page in a headless browser, exercising the map's own code paths
// rather than the routes underneath them. Nothing in the project imports this; it is
// the by-hand check, written down so it can be repeated.

import { harness } from "./browser.mjs";

const { page, stop } = await harness();
const { evaluate } = page;

let failures = 0;

function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  failures += ok ? 0 : 1;
  console.log(`${ok ? "pass" : "FAIL"}  ${name}`
    + (ok ? "" : `\n        got  ${JSON.stringify(got)}`
             + `\n        want ${JSON.stringify(want)}`));
}

async function settle(test, tries = 40) {
  for (let attempt = 0; attempt < tries; attempt += 1) {
    if (await evaluate(test)) {
      return;
    }
    await new Promise((done) => setTimeout(done, 150));
  }
}


// The page boots with a map and no selection.
check("nodes drawn", await evaluate("cy.nodes().length"), 3);
check("reciprocal exits collapse into one line", await evaluate("cy.edges().length"), 3);
check("the pair is double headed",
  await evaluate("cy.edges('[?both]').length"), 1);
check("the gated exit stays its own arrow",
  await evaluate("cy.edges('[?gate]').length"), 1);
check("the start room is marked", await evaluate("cy.nodes('[?start]').id()"), "cave_mouth");
check("panel invites a tap",
  await evaluate("document.querySelector('#panel .empty').textContent.trim()"),
  "Tap a room to edit it.");

// Tapping a node opens its room panel.
await evaluate("cy.$id('debris_room').emit('tap')");
check("tap selects the room", await evaluate("state.room"), "debris_room");
check("the panel names the room",
  await evaluate("document.querySelector('#panel h2').textContent.trim()"),
  "Debris room");
check("and asks for no id anywhere",
  await evaluate("document.querySelectorAll('#panel [data-field=id]').length"), 0);

// Every form commits the same way: a Save button, and the room's is always on screen.
check("the room has a save of its own",
  await evaluate("document.querySelectorAll('#panel .dock [data-do=save-room]').length"), 1);
check("and so does making a room",
  await evaluate(`document.querySelectorAll(
     '#panel [data-do=save-room], #panel [data-do=make-room]').length`), 2);
await evaluate(`document.querySelector('[data-form=room] [data-field=oneway]').checked = true;
                JOBS['save-room']()`);
await settle("state.world.rooms.debris_room.oneway === true");
check("saving writes the ticked box", await evaluate("state.world.rooms.debris_room.oneway"),
  true);
check("desc is loaded",
  await evaluate("document.querySelector('[data-field=desc]').value"
                 + " === state.world.rooms.debris_room.desc"),
  true);
check("exit rows drawn",
  await evaluate("document.querySelectorAll('#panel [data-exit]').length"), 2);
check("the condition is ticked, and reads as words",
  await evaluate(`[...document.querySelectorAll('#panel [data-exit]')]
     .map((row) => [...row.querySelectorAll('[data-cond]:checked')]
       .map((box) => box.parentElement.textContent.trim()).join(', ')).join('|')`),
  "|rubble cleared");
check("only what can be carried offers a have condition",
  await evaluate(`[...document.querySelectorAll('#panel [data-exit] [data-cond]')]
     .map((box) => box.parentElement.textContent.trim()).slice(0, 4)`),
  ["have brass lamp", "have short shovel", "lamp lit", "rubble cleared"]);

// Several conditions may hold one way shut.
await evaluate(`(() => {
  const row = [...document.querySelectorAll('#panel [data-exit]')]
    .find((line) => line.querySelector('[data-field=dir]').value === 'down');
  row.querySelector('[data-cond][value="have:lamp"]').checked = true;
  return JOBS['save-room']();
})()`);
await settle("Boolean((state.world.rooms.debris_room.holding || {}).down)");
check("a way can wait on a memory and a thing at once",
  await evaluate(`[state.world.rooms.debris_room.requires.down,
                   state.world.rooms.debris_room.holding.down]`),
  [["rubble_cleared"], ["lamp"]]);
check("the room's thing is ticked",
  await evaluate("document.querySelector('#panel [data-thing]:checked').value"),
  "rubble");
check("the room's action is listed by what it does",
  await evaluate("document.querySelector('#panel p.record').textContent.trim().startsWith('dig')"),
  true);

// A thing placed here can be opened and changed without leaving the room.
await evaluate("document.querySelector('#panel [data-do=edit-thing]').click()");
await settle("state.thing === 'rubble'");
check("a thing here opens for editing",
  await evaluate("document.querySelector('[data-form=thing] [data-field=name]').value"),
  "pile of rubble");
await evaluate(`document.querySelector('[data-form=thing] [data-field=name]').value = 'heap of rubble';
                JOBS['save-thing']()`);
await settle("Boolean(state.world.things.heap_of_rubble)");
check("and the change is written",
  await evaluate("state.world.things.heap_of_rubble.name"), "heap of rubble");
check("the id follows the name",
  await evaluate("Boolean(state.world.things.rubble)"), false);
check("and everything that pointed at it is rewritten",
  await evaluate(`[state.world.rooms.debris_room.things[0],
                   state.world.actions.dig_rubble.noun]`),
  ["heap_of_rubble", "heap_of_rubble"]);
await evaluate("JOBS['close-record']()");

// Tapping an edge selects its source and highlights the row.
await evaluate("cy.edges('[dir=\"down\"]').emit('tap')");
check("edge tap picks the source", await evaluate("state.room"), "debris_room");
check("edge tap highlights its row",
  await evaluate("document.querySelector('#panel .exit.chosen [data-field=dir]').value"),
  "down");

// Editing a field and saving writes the file.
await evaluate(`document.querySelector('[data-field=desc]').value = 'Rubble everywhere.';
                JOBS['save-room']()`);
await settle("state.world.rooms.debris_room.desc === 'Rubble everywhere.'");
check("save wrote the description",
  await evaluate("state.world.rooms.debris_room.desc"), "Rubble everywhere.");
check("save kept the gate",
  await evaluate("state.world.rooms.debris_room.requires.down"), ["rubble_cleared"]);
check("save kept the coordinates it was never shown",
  await evaluate("'x' in state.world.rooms.debris_room"), false);

// Making a room from a room.
await evaluate("cy.$id('grotto').emit('tap')");
await evaluate(`(() => {
  const box = document.querySelector('[data-form=new]');
  box.querySelector('[data-field=dir]').value = 'north';
  box.querySelector('[data-field=newname]').value = 'Tunnel';
  return JOBS['make-room']();
})()`);
await settle("Boolean(state.world.rooms.tunnel)");
check("the new room exists", await evaluate("state.world.rooms.tunnel.name"), "Tunnel");
check("the source gained the exit",
  await evaluate("state.world.rooms.grotto.exits.north"), "tunnel");
check("the reverse exit was made",
  await evaluate("state.world.rooms.tunnel.exits.south"), "grotto");
check("the new room was placed north",
  await evaluate("[state.world.rooms.tunnel.x, state.world.rooms.tunnel.y]"), [440, -220]);
check("the map redrew with it", await evaluate("cy.nodes().length"), 4);

// Dragging writes coordinates after the flush.
await evaluate(`cy.$id('tunnel').position({ x: 33.4, y: -77.6 });
                remember(cy.$id('tunnel'))`);
await settle("state.world.rooms.tunnel.x === 33");
check("the drag was written",
  await evaluate("[state.world.rooms.tunnel.x, state.world.rooms.tunnel.y]"), [33, -78]);
check("the dragged room is no longer loose",
  await evaluate("cy.$id('tunnel').data('loose')"), false);

// A refused write reports and changes nothing.
await evaluate(`document.querySelector('[data-field=name]').value = '';
                JOBS['save-room']()`);
await settle("document.getElementById('notice').textContent.length > 0");
check("the refusal is reported",
  await evaluate("document.getElementById('notice').textContent"),
  "missing key name in rooms.grotto");
check("the refused write changed nothing",
  await evaluate("state.world.rooms.grotto.name"), "Grotto");

// A room whose deletion would orphan another is refused by the gate, not the routes.
await evaluate("cy.$id('grotto').emit('tap'); JOBS['delete-room']()");
await settle("document.getElementById('notice').textContent.includes('unreachable')");
check("deleting a room that others hang off is refused",
  await evaluate("document.getElementById('notice').textContent"),
  "unreachable rooms: tunnel");

// Deleting a room takes the exits that led to it.
await evaluate("cy.$id('tunnel').emit('tap'); JOBS['delete-room']()");
await settle("!state.world.rooms.tunnel");
check("the leaf room went", await evaluate("Boolean(state.world.rooms.tunnel)"), false);
check("the exit that led to it went",
  await evaluate("'north' in state.world.rooms.grotto.exits"), false);

await evaluate("cy.$id('grotto').emit('tap'); JOBS['delete-room']()");
await settle("!state.world.rooms.grotto");
check("the gated room went now nothing hangs off it",
  await evaluate("Boolean(state.world.rooms.grotto)"), false);
check("its gate went with the exit",
  await evaluate("'down' in (state.world.rooms.debris_room.requires || {})"), false);

// The world panel edits what has no node.
await evaluate("document.getElementById('show-world').click()");
check("world panel opens",
  await evaluate("document.querySelector('#panel h2').textContent.trim()"), "World");
check("start room is offered",
  await evaluate("document.querySelector('[data-field=start]').value"), "cave_mouth");
await evaluate(`document.querySelector('[data-field=title]').value = 'Over the Hill';
                JOBS['save-meta']()`);
await settle("state.world.meta.title === 'Over the Hill'");
check("meta was written", await evaluate("state.world.meta.title"), "Over the Hill");
check("the version was left alone", await evaluate("state.world.meta.version"), 1);

// Footprints: a named cost that builds to a remembered flag, edited in the world panel.
await evaluate(`(() => {
  JOBS['add-mark']();
  const row = document.querySelector('[data-form=marks] [data-mark]');
  row.querySelector('[data-field=name]').value = 'attention';
  row.querySelector('[data-field=threshold]').value = '2';
  row.querySelector('[data-field=sets]').value = 'watched';
  return JOBS['save-marks']();
})()`);
await settle("Boolean((state.world.marks || {}).attention)");
check("a footprint saves with its threshold and the flag it sets",
  await evaluate("[state.world.marks.attention.threshold, state.world.marks.attention.sets]"),
  [2, "watched"]);

// An action can use a thing up and add to a footprint.
await evaluate("JOBS['new-action']()");
await settle("state.action === ''");
await evaluate(`(() => {
  const f = document.querySelector('[data-form=action]');
  f.querySelector('[data-field=verb]').value = 'ping';
  f.querySelector('[data-field=message]').value = 'It pings.';
  const noun = f.querySelector('[data-field=noun]');
  noun.value = noun.options[0].value;
  f.querySelector('[data-spend]').checked = true;
  f.querySelector('[data-raise=attention]').value = '1';
  return JOBS['save-action']();
})()`);
await settle("Object.values(state.world.actions).some((a) => a.verb === 'ping')");
check("an action can spend a thing and raise a footprint", await evaluate(`(() => {
  const a = Object.values(state.world.actions).find((x) => x.verb === 'ping');
  return [Array.isArray(a.spends) && a.spends.length === 1, a.raises];
})()`), [true, { attention: 1 }]);


// Records are made from wherever they belong, and no form ever asks for an id.
await evaluate("cy.$id('debris_room').emit('tap')");
check("no create form asks for an id",
  await evaluate("document.querySelectorAll('#panel [data-field=id]').length"), 0);
await evaluate(`document.querySelector('[data-form=new] [data-field=dir]').value = 'down';
                JOBS['make-room']()`);
await settle("Boolean(state.world.rooms.room)");
check("a direction alone is enough to make a room",
  await evaluate("Boolean(state.world.rooms.room)"), true);
check("an unnamed room takes the id it fell back to",
  await evaluate("state.world.rooms.room.name"), "room");
check("the reverse exit came with it",
  await evaluate("state.world.rooms.room.exits.up"), "debris_room");

// Typing into the room and then making a thing must not throw the room away.
await evaluate(`document.querySelector('[data-form=room] [data-field=desc]').value = 'Rubble and dust.';
                document.querySelector('[data-form=room] [data-field=oneway]').checked = true`);
await evaluate("JOBS['new-thing-here']()");
await settle("state.world.rooms.debris_room.desc === 'Rubble and dust.'");
check("opening a thing form keeps what was typed into the room",
  await evaluate("state.world.rooms.debris_room.desc"), "Rubble and dust.");
check("including the box that was ticked",
  await evaluate("state.world.rooms.debris_room.oneway"), true);

await evaluate(`document.querySelector('[data-form=thing] [data-field=name]').value = 'a coin';
                JOBS['save-thing']()`);
await settle("Boolean(state.world.things.a_coin)");
check("and saving the thing leaves the room as it was",
  await evaluate("state.world.rooms.debris_room.desc"), "Rubble and dust.");
check("a thing's id is its name", await evaluate("state.world.things.a_coin.name"), "a coin");
check("and it is placed where it was made",
  await evaluate("state.world.rooms.debris_room.things.includes('a_coin')"), true);
check("the form closed itself", await evaluate("state.thing"), null);

await evaluate("JOBS['new-action']()");
check("an action made from a room starts in that room",
  await evaluate("document.querySelector('[data-form=action] [data-field=in_room]').value"),
  "debris_room");
await evaluate(`(() => {
  const box = document.querySelector('[data-form=action]');
  box.querySelector('[data-field=verb]').value = 'rub';
  box.querySelector('[data-field=noun]').value = 'a_coin';
  box.querySelector('[data-field=sets]').value = 'rubbed';
  box.querySelector('[data-field=message]').value = 'You rub it.';
  return JOBS['save-action']();
})()`);
await settle("Boolean(state.world.actions.rub_a_coin)");
check("an action's id is its verb and its noun",
  await evaluate("state.world.actions.rub_a_coin.verb"), "rub");

await evaluate("JOBS['new-action']()");
check("the conditions start folded away",
  await evaluate("document.querySelector('[data-more]').classList.contains('away')"), true);
await evaluate(`(() => {
  const box = document.querySelector('[data-form=action]');
  box.querySelector('[data-field=verb]').value = 'polish';
  box.querySelector('[data-field=noun]').value = 'a_coin';
  box.querySelector('[data-field=message]').value = 'It gleams.';
  return JOBS['save-action']();
})()`);
await settle("Boolean(state.world.actions.polish_a_coin)");
check("three fields are enough to make an action",
  await evaluate("state.world.actions.polish_a_coin.message"), "It gleams.");
check("and it is remembered under its own name",
  await evaluate("state.world.actions.polish_a_coin.sets"), ["polish_a_coin"]);

// A name is an identity now, so no two records may share one.
await evaluate(`document.querySelector('[data-form=new] [data-field=dir]').value = 'west';
                document.querySelector('[data-form=new] [data-field=newname]').value = 'Mossy Hall';
                JOBS['make-room']()`);
await settle("Boolean(state.world.rooms.mossy_hall)");
check("a room's id is its name, lowercased and joined",
  await evaluate("state.world.rooms.mossy_hall.name"), "Mossy Hall");

await evaluate(`document.querySelector('[data-form=new] [data-field=dir]').value = 'east';
                document.querySelector('[data-form=new] [data-field=newname]').value = 'Mossy Hall';
                JOBS['make-room']()`);
await settle("document.getElementById('notice').textContent.includes('already called')");
check("a second room of the same name is refused",
  await evaluate("document.getElementById('notice').textContent"),
  "Another room is already called that.");
check("and nothing was written",
  await evaluate("Object.keys(state.world.rooms).filter((id) => id.startsWith('mossy')).length"),
  1);

await evaluate("cy.$id('cave_mouth').emit('tap')");
await evaluate(`document.querySelector('[data-form=room] [data-field=name]').value = 'Debris room';
                JOBS['save-room']()`);
check("renaming onto another room's name is refused too",
  await evaluate("document.getElementById('notice').textContent"),
  "Another room is already called that.");

// Lighting is an option a thing is given, not a question every thing is asked.
await evaluate("document.querySelectorAll('#panel [data-do=edit-thing]')[1].click()");
await settle("state.thing === 'shovel'");
check("a shovel is not asked which flag it lights by",
  await evaluate("document.querySelector('[data-lightrow]').classList.contains('away')"),
  true);
await evaluate("document.querySelector('[data-do=lighting]').click()");
check("until it is told it gives light",
  await evaluate("document.querySelector('[data-lightrow]').classList.contains('away')"),
  false);
await evaluate("JOBS['close-record']()");

await evaluate("document.querySelectorAll('#panel [data-do=edit-thing]')[0].click()");
await settle("state.thing === 'lamp'");
check("a lamp opens with its flag already showing",
  await evaluate("document.querySelector('[data-field=light_when]').value"), "lamp_lit");
check("and its box ticked",
  await evaluate("document.querySelector('[data-do=lighting]').checked"), true);

// The unless key: a way can be told to shut once a memory is set. Self-contained,
// run last, on cave_mouth's own exit so no earlier check is disturbed.
await evaluate("cy.$id('cave_mouth').emit('tap')");
await settle("state.room === 'cave_mouth'");
await evaluate(`(() => {
  const row = [...document.querySelectorAll('#panel [data-exit]')]
    .find((line) => line.querySelector('[data-field=dir]').value === 'in');
  row.querySelector('[data-shut][value="lamp_lit"]').checked = true;
  return JOBS['save-room']();
})()`);
await settle("Boolean((state.world.rooms.cave_mouth.unless || {}).in)");
check("a way can be set to shut once a memory is remembered",
  await evaluate("state.world.rooms.cave_mouth.unless.in"),
  ["lamp_lit"]);

console.log(failures === 0
  ? "\nall interaction checks passed"
  : `\n${failures} failed`);
stop();
process.exit(failures === 0 ? 0 : 1);
