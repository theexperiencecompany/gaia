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

/** Founder's booking link for the meeting CTA. */
export const MEETING_URL = "https://cal.com/aryanranderiya";

/** Ink: pure black on flat gold. No gray, no brown, no gradient. */
export const INK = "#000000";
export const INK_SOFT = "#000000";

/** Typography: the app's normal sans everywhere. */
export const BODY_FONT = "var(--font-inter), Inter, sans-serif";

/** The letter's body, one entry per paragraph. The offer paragraph is
 * rendered separately (it carries the inline code + copy button). */
export const LETTER_PARAGRAPHS: readonly string[] = [
  "If you're reading this, you were here before almost anyone else, and I want you to know how much that means to me.",
  "I'll be straight with you. There were stretches where GAIA wasn't what I promised it would be, and you felt every one of them. I won't hand you excuses for those months. What I'll say is that I took it personally, and I never once considered stopping.",
  "That work is in your hands now. GAIA is faster, steadier, it remembers, and the integrations simply work. Every change since has been for the people who stayed, which means every change has been for you.",
];

/** Salutation fallback when the user's name is unknown. */
export const SALUTATION_FALLBACK = "friend";

export const MEETING_SENTENCE =
  "And if you have fifteen minutes, I'd love to hear what you need from a personal assistant, and what you dream it could do.";

export const MEETING_CTA = "Let's set up a time to talk";

export const SIGNATURE_CAPTION = "Aryan Randeriya, Founder & CEO, GAIA";
