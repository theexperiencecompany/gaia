/**
 * The early-bird offer, in one place.
 *
 * Two surfaces sell it — the founder's letter in the app and the banner on the
 * landing pages — so the code, the percentage, the terms and the deadline live
 * here rather than in either feature. If any of it changes, it changes once.
 *
 * The percentage and the deadline must match the Dodo coupon; the coupon is
 * the authority, and a mismatch means a reader gets a dead code at checkout.
 */

/** Must exist as a coupon in Dodo Payments, in the environment being served. */
export const OFFER_CODE = "THANKYOU40";

export const OFFER_PERCENT = 40;

/**
 * What the coupon actually does, in the reader's words. It runs for a single
 * billing cycle, so it is one month off a monthly plan and one year off a
 * yearly one. Say that plainly rather than "first year", which is only true on
 * one of the two plans.
 */
export const OFFER_SCOPE =
  "your first payment, which is your first month on monthly or your whole first year on yearly";

/**
 * What the yearly plan works out to. A year already costs ten months of the
 * monthly rate (the standing annual discount); 40% off that leaves six months
 * of monthly payments, so the reader saves six. Recompute if either the annual
 * discount or OFFER_PERCENT moves.
 */
export const OFFER_YEARLY_NOTE =
  "On yearly that is six months free compared with paying month to month.";

/** The same saving, short enough for a one-line banner. */
export const OFFER_MONTHS_FREE_PHRASE = "six months free on yearly";

/** Last moment the code works, matching `expires_at` on the Dodo coupon. */
export const OFFER_EXPIRES_AT = "2026-11-12T23:59:59Z";

/**
 * How the deadline is said out loud. Deliberately not a date: a printed date
 * ages the letter the moment it passes, and the real gate is OFFER_EXPIRES_AT,
 * which removes the offer on its own.
 */
export const OFFER_DEADLINE_PHRASE = "while it lasts";

/** Whether the offer is still live. Every surface gates on this, so an expired
 * offer disappears on its own instead of waiting for a deploy. */
export function isOfferLive(now: Date = new Date()): boolean {
  return now.getTime() < Date.parse(OFFER_EXPIRES_AT);
}
