// Screenshots the editor page, optionally after running an expression in it.
//
//   node --experimental-websocket tools/harness/shot.mjs map.png
//   node --experimental-websocket tools/harness/shot.mjs panel.png "cy.\$id('grotto').emit('tap')"

import { writeFileSync } from "node:fs";

import { harness } from "./browser.mjs";

const [target = "map.png", expression] = process.argv.slice(2);
const { page, stop } = await harness();

if (expression) {
  await page.evaluate(expression);
}
await new Promise((done) => setTimeout(done, 600));

const shot = await page.call("Page.captureScreenshot", { format: "png" });
writeFileSync(target, Buffer.from(shot.result.data, "base64"));
console.log(`wrote ${target}`);
stop();
process.exit(0);
