// Pricing math constants — the annual-discount relationship lives here so the
// pricing cards can't encode it inconsistently.

/** Months billed up front on an annual plan. */
export const MONTHS_PER_YEAR = 12;

/** Backend prices are in cents; divide by this to get dollars. */
export const CENTS_PER_DOLLAR = 100;

/** Discount every paid annual plan carries versus paying monthly. */
export const ANNUAL_DISCOUNT_RATE = 0.25;

/**
 * Fraction of the monthly list price an annual plan actually charges
 * (1 - ANNUAL_DISCOUNT_RATE). The pre-discount yearly list price is therefore
 * `annualPrice / ANNUAL_PRICE_RETENTION`.
 */
export const ANNUAL_PRICE_RETENTION = 1 - ANNUAL_DISCOUNT_RATE;
