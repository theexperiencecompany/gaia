const SHARE_URL = "https://heygaia.io";

/** The X share copy for an activity badge — one line shared by both the rendered
 *  image-card path and the text-only fallback so they can never drift apart. */
export function buildTweetText(tierLabel: string, streak: number): string {
  return `I'm in the ${tierLabel} of GAIA users by activity — a ${streak}-day streak. Meet your proactive AI assistant.`;
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
