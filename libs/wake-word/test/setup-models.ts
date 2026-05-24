/**
 * Vitest globalSetup — runs once before any tests start.
 *
 * Models are gitignored (too large for the repo's >500 KB policy). This setup
 * ensures they are downloaded before tests try to load them, so contributors
 * just run `pnpm test` and it Just Works.
 */
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

// Absolute interpreter path — avoids resolving "bash" via $PATH (which could
// point at an attacker-writable directory) and is present on macOS and CI Linux.
const BASH_PATH = "/bin/bash";

export default function setup(): void {
  const script = resolve(__dirname, "..", "scripts", "fetch-models.sh");
  execFileSync(BASH_PATH, [script], { stdio: "inherit" });
}
