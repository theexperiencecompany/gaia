/**
 * Vitest globalSetup — runs once before any tests start.
 *
 * Models are gitignored (too large for the repo's >500 KB policy). This setup
 * ensures they are downloaded before tests try to load them, so contributors
 * just run `pnpm test` and it Just Works.
 */
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

export default function setup(): void {
  const script = resolve(__dirname, "..", "scripts", "fetch-models.sh");
  execFileSync("bash", [script], { stdio: "inherit" });
}
