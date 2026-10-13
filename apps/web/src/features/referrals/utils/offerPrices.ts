import type { ReferralOffer } from "@shared/api/generated";
import { formatWholeOrCents } from "@/features/pricing/utils/money";

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
