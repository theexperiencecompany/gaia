const SHARE_URL = "https://heygaia.io";

/** The X share copy — one builder shared by both the rendered image-card path
 *  and the text-only fallback so they can never drift apart.
 *
 *  `tierLabel` null (the common case, most users unranked) drops the "top X%"
 *  clause rather than filling a placeholder; a zero-day streak likewise drops its clause instead of boasting "a 0-day streak". */
export function buildTweetText(
  tierLabel: string | null,
  streak: number,
): string {
  const standing = tierLabel
    ? `I'm in the ${tierLabel} of GAIA users by activity`
    : "I'm building my streak on GAIA";
  const streakClause = streak > 0 ? `, a ${streak}-day streak.` : ".";
  return `${standing}${streakClause} Meet your proactive AI assistant.`;
}

/** Open the X/Twitter compose intent prefilled with `text` and the GAIA link. */
export function openTweetIntent(text: string): void {
  if (typeof window === "undefined") return;
  window.open(
    `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(SHARE_URL)}`,
    "_blank",
    "noopener,noreferrer",
  );
}
