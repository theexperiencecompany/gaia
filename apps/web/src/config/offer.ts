/**
 * The early-bird offer, in one place.
 *
 * The founder's letter sells it, so the code, the percentage, the terms and the
 * deadline live here rather than inside that feature. If any of it changes, it
 * changes once.
 *
 * The percentage and the deadline must match the Dodo coupon; the coupon is
 * the authority, and a mismatch means a reader gets a dead code at checkout.
 */

/** Must exist as a coupon in Dodo Payments, in the environment being served. */
export const OFFER_CODE = "THANKYOU40";

export const OFFER_PERCENT = 40;

/**
 * The one number worth putting in the sentence. A year already costs ten months
 * of the monthly rate (the standing annual discount); 40% off that leaves six
 * months, so the reader saves six. Recompute if either the annual discount or
 * OFFER_PERCENT moves.
 */
export const OFFER_YEARLY_NOTE = "On yearly that's six months free.";

/**
 * The mechanics, kept out of the sentence and set under the button where terms
 * belong: the coupon runs for a single billing cycle, which is one month on a
 * monthly plan and a full year on a yearly one.
 */
export const OFFER_TERMS =
  "Covers your first payment: one month on monthly, a full year on yearly. While it lasts.";

/** Last moment the code works, matching `expires_at` on the Dodo coupon.
 * Read only through `isOfferLive` — the date itself is never rendered. */
const OFFER_EXPIRES_AT = "2026-11-12T23:59:59Z";

/** Whether the offer is still live. Every surface gates on this, so an expired
 * offer disappears on its own instead of waiting for a deploy. */
export function isOfferLive(now: Date = new Date()): boolean {
  return now.getTime() < Date.parse(OFFER_EXPIRES_AT);
}
