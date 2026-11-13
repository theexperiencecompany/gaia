import advertised from "@shared-assets/pricing/pro-monthly-price.json";

import { toMajorUnits } from "./utils/money";

/**
 * The Pro monthly price the static marketing pages quote, in major units.
 *
 * Those pages are prebuilt, so they cannot read the live catalogue; the shared
 * file is the one copy, and scripts/payment_setup.py refuses to write a
 * catalogue whose Dodo monthly price differs from it.
 */
export const ADVERTISED_PRO_MONTHLY_PRICE = toMajorUnits(
  advertised.amount,
  advertised.currency,
);

/** The same advertised price in minor units with its currency, for figures derived from it. */
export const ADVERTISED_PRO_MONTHLY = {
  amount: advertised.amount,
  currency: advertised.currency,
} as const;

/** Where marketing data writes GAIA's own monthly price, number only, so each locale keeps its own format. */
export const PRO_MONTHLY_PRICE_TOKEN = "{{PRO_MONTHLY_PRICE}}";
