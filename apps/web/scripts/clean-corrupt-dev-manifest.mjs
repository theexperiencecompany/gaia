/**
 * Dev-only guard for Next.js's `.next/dev/prerender-manifest.json`.
 *
 * The Turbopack dev server writes this file, then reads it on every request
 * *without regenerating it*. If a run is interrupted mid-write (e.g. the dev
 * server is force-killed), the file is left corrupt — valid JSON followed by a
 * duplicated tail — and it is never repaired, so every route then fails with
 *
 *   SyntaxError: Unexpected non-whitespace character after JSON at position N
 *
 * which surfaces as a 500 on every route until `.next` is wiped. Removing it
 * before the server starts forces a clean regeneration.
 */

import { rmSync } from "node:fs";
import { join } from "node:path";

const manifestPath = join(
  process.cwd(),
  ".next",
  "dev",
  "prerender-manifest.json",
);

rmSync(manifestPath, { force: true });
