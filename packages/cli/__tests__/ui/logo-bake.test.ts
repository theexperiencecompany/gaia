import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { logoLines } from "../../src/ui/header/logo.js";

const CLI_ROOT = fileURLToPath(new URL("../..", import.meta.url));
const INSTALLER = path.join(CLI_ROOT, "install.sh");

// The bake searches every scale and sub-pixel offset: ~30s of CPU.
const BAKE_TIMEOUT_MS = 180_000;

const LITERAL_ESCAPE = "\\033";
const ESCAPE = "\u001b";

/** The lines of one LOGO_<variant>='…' block baked into install.sh. */
function installerLogo(source: string, variant: string): string[] {
  const logo = source.match(
    new RegExp(`^LOGO_${variant}='([^']*)'$`, "m"),
  )?.[1];
  if (logo === undefined) throw new Error(`install.sh has no LOGO_${variant}`);
  return logo.split("\n").map((l) => l.replaceAll(LITERAL_ESCAPE, ESCAPE));
}

describe("bake-logo", () => {
  it(
    "regenerates the committed logo table and install.sh byte for byte",
    () => {
      expect(() =>
        execFileSync(process.execPath, ["scripts/bake-logo.mjs", "--check"], {
          cwd: CLI_ROOT,
          stdio: "pipe",
        }),
      ).not.toThrow();
    },
    BAKE_TIMEOUT_MS,
  );

  it.each([
    ["TRUECOLOR", 3],
    ["ANSI256", 2],
    ["ANSI16", 1],
    ["PLAIN", 0],
  ] as const)("install.sh draws the CLI's logo in %s", (variant, level) => {
    expect(installerLogo(fs.readFileSync(INSTALLER, "utf8"), variant)).toEqual(
      logoLines(level),
    );
  });
});
