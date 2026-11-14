import type { ReferralFriendGift, ReferralOffer } from "@shared/api/generated";
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

/** The gift as the pricing card shows it, on only the cycles checkout applies it to. */
export function giftCardPrice({
  offer,
  billing_cycles,
}: ReferralFriendGift): GiftPrice {
  return {
    monthly: billing_cycles.includes("monthly")
      ? {
          minor: offer.monthly_intro_minor,
          note: REFERRAL_UI_COPY.paywallMonthlyNote(offerPrices(offer)),
        }
      : null,
    yearly: billing_cycles.includes("yearly")
      ? {
          minor: offer.yearly_regular_minor - offer.yearly_discount_minor,
          note: REFERRAL_UI_COPY.paywallYearlyNote(
            formatWholeOrCents(offer.yearly_regular_minor, offer.currency),
          ),
        }
      : null,
  };
}
