import { ADVERTISED_PRO_MONTHLY } from "../advertisedPrice";
import { formatWholeOrCents } from "../utils/money";
import { getDailyPrice } from "../utils/priceDisplay";

interface ProDailyPriceHeadingProps {
  /** The words after the per-day price ("a day to never work again."). */
  afterPrice: string;
}

/**
 * A heading led by the Pro monthly price per day ("$1"). It quotes the
 * advertised price payment_setup.py holds Dodo to, not the plans API, so the
 * server render, the hydrated page and every plans-query state read the same.
 */
export function ProDailyPriceHeading({
  afterPrice,
}: ProDailyPriceHeadingProps) {
  const dailyPrice = getDailyPrice(ADVERTISED_PRO_MONTHLY.amount);
  return `${formatWholeOrCents(dailyPrice, ADVERTISED_PRO_MONTHLY.currency)} ${afterPrice}`;
}
