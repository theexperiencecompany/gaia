import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const CLI_ROOT = fileURLToPath(new URL("../..", import.meta.url));
const COMMITTED = path.join(CLI_ROOT, "src/ui/header/logo-cells.generated.ts");

// The bake searches every scale and sub-pixel offset of both sizes: ~30s of CPU.
const BAKE_TIMEOUT_MS = 180_000;

describe("bake-logo", () => {
  it(
    "regenerates the committed logo table byte for byte",
    () => {
      const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gaia-logo-"));
      const out = path.join(dir, "logo-cells.generated.ts");
      try {
        execFileSync(process.execPath, ["scripts/bake-logo.mjs", out], {
          cwd: CLI_ROOT,
        });
        expect(fs.readFileSync(out, "utf8")).toBe(
          fs.readFileSync(COMMITTED, "utf8"),
        );
      } finally {
        fs.rmSync(dir, { recursive: true, force: true });
      }
    },
    BAKE_TIMEOUT_MS,
  );
});
