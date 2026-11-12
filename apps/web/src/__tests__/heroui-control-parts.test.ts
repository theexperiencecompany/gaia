import { globSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// A v3 Switch or Checkbox renders only the parts it is given: written
// self-closing (the v2 shape) it renders an empty div, with no input, no
// control and no accessible role, so the setting silently disappears.
const SRC_DIR = path.resolve(__dirname, "..");
const CONTROL_OPEN = /<(Switch|Checkbox)(?![.\w])/g;

function selfClosingControls(source: string): string[] {
  const found: string[] = [];
  for (const match of source.matchAll(CONTROL_OPEN)) {
    let depth = 0;
    let index = (match.index ?? 0) + match[0].length;
    for (; index < source.length; index++) {
      const char = source[index];
      if (char === "{") depth++;
      else if (char === "}") depth--;
      else if (char === ">" && depth === 0) break;
    }
    if (source[index - 1] === "/") {
      const line = source.slice(0, match.index).split("\n").length;
      found.push(`${match[1]} at line ${line}`);
    }
  }
  return found;
}

describe("HeroUI v3 controls render their parts", () => {
  const files = globSync("**/*.tsx", { cwd: SRC_DIR }).filter((file) =>
    readFileSync(path.join(SRC_DIR, file), "utf8").includes('"@heroui/react"'),
  );

  it("never writes a Switch or Checkbox without its Control", () => {
    const offenders = files.flatMap((file) =>
      selfClosingControls(readFileSync(path.join(SRC_DIR, file), "utf8")).map(
        (where) => `${file}: ${where}`,
      ),
    );
    expect(offenders).toEqual([]);
  });
});
