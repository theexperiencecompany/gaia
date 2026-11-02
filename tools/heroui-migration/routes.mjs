#!/usr/bin/env node
/** Derive screenshot-able routes from the Next.js app dir. Zero deps. */
import { readdirSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

const APP = "apps/web/src/app";
const files = [];
function walk(dir) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name.startsWith(".")) continue;
    const p = join(dir, e.name);
    if (e.isDirectory()) walk(p);
    else if (e.name === "page.tsx") files.push(p);
  }
}
walk(APP);

const routes = [...new Set(
  files.map((f) => {
    const rel = relative(APP, f).replace(/\/?page\.tsx$/, "");
    return "/" + rel.split("/").filter((s) => s && s !== "[locale]" && !/^\(.*\)$/.test(s)).join("/");
  }),
)]
  .filter((r) => !r.startsWith("/dev") && !/<|\[/.test(r))
  .sort();

writeFileSync("tools/heroui-migration/routes.json", JSON.stringify(routes, null, 2));
console.log(`${routes.length} routes -> tools/heroui-migration/routes.json`);
console.log(routes.slice(0, 12).join("\n"));
