/**
 * The founder's letter. Every word of the copy lives here so it can be
 * edited without touching the letter's structure or styling.
 *
 * Style rules for this copy: no em dashes, no ALL-CAPS labels, warm and
 * honest. The letter is meant to read like a real letter, not a marketing page.
 */

/** Discount code offered in the letter. Must exist as a coupon in Dodo Payments. */
export const DISCOUNT_CODE = "THANKYOU40";

/** The discount percentage shown alongside the code (copy only; the actual
 * terms live in the Dodo coupon). */
export const DISCOUNT_PERCENT = 40;

/** The discount applies to both billing periods. */
export const DISCOUNT_APPLIES = "monthly and yearly plans";

/** Founder's real address, used by the app's support routes too. */
export const FOUNDER_EMAIL = "aryan@heygaia.io";

export const MEETING_MAILTO = `mailto:${FOUNDER_EMAIL}?subject=${encodeURIComponent("GAIA: I'd love to talk")}&body=${encodeURIComponent("Hi Aryan,\n\nI read your letter. I'd love to set up a short call to talk about what I need from a personal assistant.\n\nThanks!")}`;

/** Dated like a real letter. */
export const LETTER_DATE = "12 August 2026";

/** localStorage key: pulses the envelope until the letter has been opened once. */
export const LETTER_OPENED_KEY = "gaia_founder_letter_opened";

/** Ink + paper tones. Kept here so the letter keeps one voice. */
export const INK = "#46301f";
export const INK_SOFT = "#8a6a3f";

/** The vibrant accent (coral) used for the letterhead, link and buttons. */
export const ACCENT = "#e2533f";

/** Typography. The letter is set in the app's own editorial serif, with the
 * GAIA mark in PP Editorial and the discount code in the app's mono. */
export const BODY_FONT = "var(--font-instrument-serif), Georgia, serif";
export const MARK_FONT = "var(--font-pp-editorial-new), Georgia, serif";
export const CODE_FONT = "var(--font-geist-mono), ui-monospace, monospace";

/** The letter's body, one entry per paragraph. */
export const LETTER_PARAGRAPHS: readonly string[] = [
  "If you're reading this, you were here before almost anyone else, and I want you to know how much that means to me.",
  "I also owe you honesty. GAIA hasn't always been what you deserved. We ran out of money. APIs we depended on cut us off overnight. Life kept throwing punches. I'm sorry for all of it, truly.",
  "But here's what I'm proudest of: we're still here, and better than ever. Speed, reliability, a memory that remembers, integrations that just work. Every change since has been for you.",
  "As a thank-you for believing in us when it wasn't easy, take 40% off your first year, on both monthly and yearly plans.",
];

export const SALUTATION = "Dear friend,";

export const MEETING_SENTENCE =
  "And if you have fifteen minutes, I'd love to hear what you need from a personal assistant, and what you dream it could do.";

export const MEETING_CTA = "Let's set up a time to talk";

export const HANDWRITTEN_NOTE =
  "The signature below is mine, written by hand. From my desk to yours.";

export const SIGNATURE_CAPTION = "Aryan Randeriya · Founder & CEO, GAIA";
