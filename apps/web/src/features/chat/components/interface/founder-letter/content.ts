/**
 * The founder's letter. Every word of the copy lives here so it can be
 * edited without touching the letter's structure or styling.
 *
 * Style rules for this copy: contractions, no em dashes, no ALL-CAPS labels.
 * Vary sentence length; no claims about the writer's own virtue; no vague
 * abstractions standing in for facts. It should read like a person typing,
 * not a marketing page.
 */

/**
 * The offer itself lives in `@/config/offer` because the landing banner sells
 * the same one; the letter only re-exports it under its own names.
 */
export {
  OFFER_CODE as DISCOUNT_CODE,
  OFFER_DEADLINE_PHRASE as DISCOUNT_DEADLINE,
  OFFER_PERCENT as DISCOUNT_PERCENT,
  OFFER_SCOPE as DISCOUNT_SCOPE,
  OFFER_YEARLY_NOTE as DISCOUNT_YEARLY_NOTE,
} from "@/config/offer";

/** Founder's booking link for the meeting CTA. */
export const MEETING_URL = "https://cal.com/aryanranderiya";

/** localStorage key: set the first time the letter is opened on this device. */
export const LETTER_OPENED_KEY = "gaia_founder_letter_opened";

/** localStorage key: once dismissed, the envelope never returns on this device. */
export const LETTER_DISMISSED_KEY = "gaia_founder_letter_dismissed";

/** Ink: pure black on flat gold. No gray, no brown, no gradient. */
export const INK = "#000000";
export const INK_SOFT = "#000000";

/** Typography: the app's normal sans everywhere. */
export const BODY_FONT = "var(--font-inter), Inter, sans-serif";

/** The letter's body, one entry per paragraph. The offer paragraph is
 * rendered separately (it carries the inline code + copy button). */
export const LETTER_PARAGRAPHS: readonly string[] = [
  "You've been here since the early days, and you're still here. Thank you for that.",
  "For a long stretch, GAIA wasn't reliable. Slow when you needed it, forgetful when it mattered. You worked around it instead of leaving.",
  "Reliability is the whole job now. It's fast, it remembers, and it finishes what you asked without you checking. I run my entire day on it.",
];

/** Salutation fallback when the user's name is unknown. */
export const SALUTATION_FALLBACK = "friend";

/** The offer, split around the inline code + copy button. Opens by letting the
 * reader off the hook, so the paragraph above doesn't read as a set-up. */
export const OFFER_LEAD = "No strings on any of this.";
export const OFFER_TAIL = "at checkout, any time before";

export const MEETING_SENTENCE =
  "If you've got fifteen minutes, tell me what you'd want it to take off your plate.";

export const MEETING_CTA = "Pick a time that works";

/** Signature block: the name, then the role, on their own lines. */
export const SIGNATURE_NAME = "Aryan Randeriya";
export const SIGNATURE_ROLE = "Founder & CEO - GAIA";
