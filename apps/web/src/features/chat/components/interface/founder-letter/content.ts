/**
 * The founder's letter. Every word of the copy lives here so it can be
 * edited without touching the letter's structure or styling.
 *
 * Style rules for this copy: no em dashes, no ALL-CAPS labels, warm and
 * honest. The letter is meant to read like a real letter, not a marketing page.
 */

/**
 * The offer itself lives in `@/config/offer` because the landing banner sells
 * the same one; the letter only re-exports it under its own names.
 */
export {
  OFFER_CODE as DISCOUNT_CODE,
  OFFER_EXPIRES_LABEL as DISCOUNT_EXPIRES,
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
  "You were here before almost anyone else. That is not a small thing to me, and I have not forgotten it.",
  "You did not get the GAIA you signed up for right away. Some months were slower and quieter than they should have been, and that is on me. I spent them rebuilding the parts that kept breaking rather than shipping noise, and I never once considered stopping.",
  "The work since has gone into stability, and you can feel it: GAIA is faster, it holds on to what you tell it, and it stays up. I run my own days on it, automating a real chunk of my work with it daily, which is the only reason I can promise it is finally worth your time.",
];

/** Salutation fallback when the user's name is unknown. */
export const SALUTATION_FALLBACK = "friend";

/** The offer, split around the inline code + copy button. Deliberately opens
 * by letting the reader off the hook: the apology above is not a set-up. */
export const OFFER_LEAD = "There are no strings on any of this.";
export const OFFER_TAIL = "at checkout, any time before";

export const MEETING_SENTENCE =
  "And if you have fifteen minutes, I'd love to hear what you need from a personal assistant, and what you dream it could do.";

export const MEETING_CTA = "Let's set up a time to talk";

/** Signature block: the name, then the role, on their own lines. */
export const SIGNATURE_NAME = "Aryan Randeriya";
export const SIGNATURE_ROLE = "Founder & CEO - GAIA";
