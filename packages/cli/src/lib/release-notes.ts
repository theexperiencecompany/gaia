/**
 * A release's highlights for `gaia update`, read from its GitHub release:
 * release-please writes each change as a bullet under Features or Bug Fixes.
 * @module lib/release-notes
 */

import { releaseGitTag } from "./release.js";

const RELEASES_API =
  "https://api.github.com/repos/theexperiencecompany/gaia/releases/tags";
const FETCH_TIMEOUT_MS = 5000;
const MAX_HIGHLIGHTS = 5;

/** Sections in the order they are worth reading. */
const SECTIONS = ["Features", "Bug Fixes"] as const;

const BULLET_RE = /^\* (.+)$/;
const SCOPE_RE = /^\*\*[^*]+:\*\*\s*/;
/** The issue and commit links release-please appends: " ([#1208](…)) ([9e97335](…))". */
const TRAILING_LINKS_RE = /(\s*\(\[[^\]]+\]\([^)]+\)\))+$/;

function sentence(bullet: string): string {
  const text = bullet.replace(SCOPE_RE, "").replace(TRAILING_LINKS_RE, "");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Up to five changes from a release body: features first, then fixes. */
export function releaseHighlights(body: string): string[] {
  const bySection = new Map<string, string[]>();
  let section = "";
  for (const line of body.split("\n")) {
    const heading = /^#{2,3} (.+)$/.exec(line.trim());
    if (heading?.[1]) {
      section = heading[1];
      continue;
    }
    const bullet = BULLET_RE.exec(line.trim())?.[1];
    if (bullet)
      bySection.set(section, [
        ...(bySection.get(section) ?? []),
        sentence(bullet),
      ]);
  }
  return SECTIONS.flatMap((name) => bySection.get(name) ?? []).slice(
    0,
    MAX_HIGHLIGHTS,
  );
}

/** The highlights of a GAIA release (v<x.y.z>) from its GitHub release. */
export async function fetchReleaseHighlights(
  imageTag: string,
): Promise<string[]> {
  const res = await fetch(`${RELEASES_API}/${releaseGitTag(imageTag)}`, {
    headers: { Accept: "application/vnd.github+json" },
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`GitHub answered HTTP ${res.status}`);
  const { body } = (await res.json()) as { body: string | null };
  return releaseHighlights(body ?? "");
}
