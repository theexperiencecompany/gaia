/**
 * The early-bird offer's terms, in one place.
 *
 * The founder's letter sells it. The code itself is a server setting
 * (FOUNDER_LETTER_DISCOUNT_CODE, read from GET /payments/discount-codes); the
 * percentage and the deadline here must match that Dodo coupon. The coupon is
 * the authority, and a mismatch means a reader gets a dead code at checkout.
 */

export const OFFER_PERCENT = 40;

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
