/**
 * Copies the two graph libraries into `app/static/vendor/` as plain browser
 * scripts, so a clone runs without npm and without a bundler touching them.
 *
 * They are vendored rather than bundled for one reason: Cytoscape is ~400 KB and
 * changes only when we upgrade it. Bundling it into `dist/app.js` would rebuild it
 * on every save during `npm run watch`.
 *
 *   node scripts/vendor.mjs
 */
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const vendor = join(root, "app", "static", "vendor");

mkdirSync(vendor, { recursive: true });

// Order matters: fcose is a UMD bundle whose externals are `layout-base` and
// `cose-base`, which publish themselves on `window`. Load them first.
const files = [
  ["node_modules/cytoscape/dist/cytoscape.min.js", "cytoscape.min.js"],
  ["node_modules/layout-base/layout-base.js", "layout-base.js"],
  ["node_modules/cose-base/cose-base.js", "cose-base.js"],
  ["node_modules/cytoscape-fcose/cytoscape-fcose.js", "cytoscape-fcose.js"],
];

for (const [from, to] of files) {
  copyFileSync(join(root, from), join(vendor, to));
  console.log(`vendored ${to}`);
}
