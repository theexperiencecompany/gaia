import { readFileSync } from "node:fs";
import path from "node:path";

export interface LatestRelease {
  apiVersion: string;
  headline: string;
  date: string;
}

const RELEASE_NOTES_PATH = path.resolve(
  process.cwd(),
  "../../docs/release-notes.mdx",
);

// Cached at module scope — release-notes.mdx is part of the repo and only
// changes on deploy, so we read it once per server boot.
let cached: LatestRelease | null | undefined;

export function getLatestRelease(): LatestRelease | null {
  if (cached !== undefined) return cached;

  try {
    const raw = readFileSync(RELEASE_NOTES_PATH, "utf8");

    const updateMatch = raw.match(/<Update\s+label="([^"]+)"[^>]*>/);
    if (!updateMatch) {
      cached = null;
      return null;
    }
    const date = updateMatch[1];

    const afterUpdate = raw.slice(updateMatch.index! + updateMatch[0].length);
    const headlineMatch = afterUpdate.match(/^\s*#\s+(.+?)\s*$/m);
    const apiVersionMatch = afterUpdate.match(
      /##\s+\[API\s+v(\d+\.\d+\.\d+)\]/,
    );

    if (!headlineMatch || !apiVersionMatch) {
      cached = null;
      return null;
    }

    cached = {
      apiVersion: apiVersionMatch[1],
      headline: headlineMatch[1].trim(),
      date,
    };
    return cached;
  } catch {
    cached = null;
    return null;
  }
}
