import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { logoLines } from "../../src/ui/header/logo.js";

const CLI_ROOT = fileURLToPath(new URL("../..", import.meta.url));
const COMMITTED = path.join(CLI_ROOT, "src/ui/header/logo-cells.generated.ts");
const INSTALLER = path.join(CLI_ROOT, "install.sh");

// The bake searches every scale and sub-pixel offset of both sizes: ~30s of CPU.
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
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-logo-"));
      const out = path.join(dir, "logo-cells.generated.ts");
      const installer = path.join(dir, "install.sh");
      fs.copyFileSync(INSTALLER, installer);
      try {
        execFileSync(
          process.execPath,
          ["scripts/bake-logo.mjs", out, installer],
          { cwd: CLI_ROOT },
        );
        expect(fs.readFileSync(out, "utf8")).toBe(
          fs.readFileSync(COMMITTED, "utf8"),
        );
        expect(fs.readFileSync(installer, "utf8")).toBe(
          fs.readFileSync(INSTALLER, "utf8"),
        );
      } finally {
        fs.rmSync(dir, { recursive: true, force: true });
      }
    },
    BAKE_TIMEOUT_MS,
  );

  it.each([
    ["TRUECOLOR", 3],
    ["ANSI256", 2],
    ["PLAIN", 0],
  ] as const)(
    "install.sh draws the CLI's small logo in %s",
    (variant, level) => {
      expect(
        installerLogo(fs.readFileSync(INSTALLER, "utf8"), variant),
      ).toEqual(logoLines("small", level));
    },
  );
});
