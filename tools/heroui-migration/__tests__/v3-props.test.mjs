import assert from "node:assert/strict";
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import jscodeshift from "jscodeshift";

import transform from "../codemods/v3-props.cjs";

const here = dirname(fileURLToPath(import.meta.url));
const fixture = join(here, "..", "__fixtures__", "flat-button-group.tsx");
const logFile = join(here, "..", "manual-review.log");

function run(source) {
  const j = jscodeshift.withParser("tsx");
  return transform(
    { path: fixture, source },
    { jscodeshift: j, j, stats: () => {} },
  );
}

test("a flat ButtonGroup applies its fill to every action button", () => {
  // The codemod logs manual props to a local file; keep that file untouched.
  const logBefore = existsSync(logFile) ? readFileSync(logFile, "utf8") : null;

  try {
    const output = run(readFileSync(fixture, "utf8"));

    assert.ok(output, "the fixture should change");

    // Group colour reaches the direct child and the Dropdown trigger.
    assert.equal(output.match(/variant="accent-soft"/g)?.length, 2);
    assert.match(output, /<Button onPress=\{connect\} variant="accent-soft">/);
    assert.match(output, /<Button isIconOnly variant="accent-soft">/);

    // Child colours override the group and become the matching soft fill.
    assert.match(output, /<Button variant="danger-soft">Disconnect<\/Button>/);
    assert.match(output, /<Button variant="default-soft">Share<\/Button>/);

    // An explicit variant is not overwritten.
    assert.match(output, /<Button variant="ghost">Cancel<\/Button>/);

    // v2 colour and flat variant are consumed; v3's ButtonGroup has neither.
    assert.doesNotMatch(output, /variant="flat"/);
    assert.doesNotMatch(output, /color="/);

    // A Button inside a menu is not part of the group's action row.
    assert.match(output, /<Button>Menu action<\/Button>/);
  } finally {
    if (logBefore === null) rmSync(logFile, { force: true });
    else writeFileSync(logFile, logBefore);
  }
});
