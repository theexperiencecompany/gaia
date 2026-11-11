"use client";

import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

import {
  getOfferPrice,
  getPriceDisplay,
  type PriceDisplay,
} from "../utils/priceDisplay";

/** What a viewer pays on one billing cycle while their gift lasts, and the line saying for how long. */
export interface GiftCyclePrice {
  /** Minor units of each monthly charge, or of the first yearly one, while the gift lasts. */
  minor: number;
  note: string;
}

/** A price only this viewer pays, such as a referred friend's gift; null on a cycle checkout does not apply it to. */
export interface GiftPrice {
  monthly: GiftCyclePrice | null;
  yearly: GiftCyclePrice | null;
}

interface PricingCardPriceInput {
  price: number;
  originalPrice: number | undefined;
  durationIsMonth: boolean;
  currency: string;
  gift: GiftPrice | null;
}

interface PricingCardPrice {
  list: PriceDisplay;
  /**
   * The same figures recomputed at the offer price, or `null` when no offer
   * is riding along (or the tier is free). Non-null is what tells the card to
   * strike the list price.
   */
  offer: PriceDisplay | null;
  /** Replaces the billing sub-line while a gift price is shown. */
  note: string | null;
}

/**
 * The list and offer price figures for one pricing card.
 *
 * An offer the modal was opened with (the founder's letter, for one) rides
 * along to checkout so the code is already applied when the page loads. The
 * discounted figures run through the same price maths as the list ones, so
 * the card can strike the list price and show what the reader will pay.
 */
export function usePricingCardPrice({
  price,
  originalPrice,
  durationIsMonth,
  currency,
  gift,
}: PricingCardPriceInput): PricingCardPrice {
  // Only an offer that names a percentage can restate the prices; the
  // enforcement path's offer (a checkout link, a code) leaves them as-is.
  const discountPercent = useUpgradeModalStore(
    (s) => s.offer?.discountPercent ?? null,
  );
  const list = getPriceDisplay(price, originalPrice, durationIsMonth, currency);
  const cycleGift = durationIsMonth ? gift?.monthly : gift?.yearly;
  if (cycleGift && price > 0)
    return {
      list,
      offer: getPriceDisplay(
        cycleGift.minor,
        originalPrice,
        durationIsMonth,
        currency,
      ),
      note: cycleGift.note,
    };
  return {
    list,
    note: null,
    offer:
      discountPercent && price > 0
        ? getPriceDisplay(
            getOfferPrice(price, discountPercent),
            originalPrice,
            durationIsMonth,
            currency,
          )
        : null,
  };
}
