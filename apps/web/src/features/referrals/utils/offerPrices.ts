import type { ReferralOffer } from "@shared/api/generated";
import type { GiftPrice } from "@/features/pricing/hooks/usePricingCardPrice";
import { formatWholeOrCents } from "@/features/pricing/utils/money";
import { REFERRAL_UI_COPY } from "../referralCopy";

/** The friend's monthly gift as display strings, read from the live offer (never hardcoded). */
export interface OfferPrices {
  /** Discounted monthly price during the intro, "$15". */
  intro: string;
  /** Normal monthly price after the intro, "$30". */
  regular: string;
  /** How many monthly charges carry the intro price. */
  cycles: number;
}

export function offerPrices(offer: ReferralOffer): OfferPrices {
  return {
    intro: formatWholeOrCents(offer.monthly_intro_minor, offer.currency),
    regular: formatWholeOrCents(offer.monthly_regular_minor, offer.currency),
    cycles: offer.intro_cycles,
  };
}

/** The gift as the pricing card shows it: what a friend pays while it lasts, and for how long. */
export function giftCardPrice(offer: ReferralOffer): GiftPrice {
  return {
    monthly: offer.monthly_intro_minor,
    yearly: offer.yearly_regular_minor - offer.yearly_discount_minor,
    monthlyNote: REFERRAL_UI_COPY.paywallMonthlyNote(offerPrices(offer)),
    yearlyNote: REFERRAL_UI_COPY.paywallYearlyNote(
      formatWholeOrCents(offer.yearly_regular_minor, offer.currency),
    ),
  };
}
