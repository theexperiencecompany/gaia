import { CANONICAL_REDIRECT_PAIRS } from "../../canonical-redirects.mjs";

const WINNER_BY_VICTIM: ReadonlyMap<string, string> = new Map(
  CANONICAL_REDIRECT_PAIRS,
);

/** The live URL for an internal path: a consolidated victim resolves to the page it 308s to. */
export function canonicalHref(path: string): string {
  return WINNER_BY_VICTIM.get(path) ?? path;
}

/** Whether a path is a consolidated victim, which never renders and so must never be linked. */
export function isRedirectedPath(path: string): boolean {
  return WINNER_BY_VICTIM.has(path);
}
