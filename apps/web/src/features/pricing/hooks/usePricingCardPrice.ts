"use client";

import { usePricingModalStore } from "@/stores/pricingModalStore";

import {
  getOfferPrice,
  getPriceDisplay,
  type PriceDisplay,
} from "../utils/priceDisplay";

interface PricingCardPriceInput {
  price: number;
  originalPrice: number | undefined;
  durationIsMonth: boolean;
}

interface PricingCardPrice {
  list: PriceDisplay;
  /**
   * The same figures recomputed at the offer price, or `null` when no offer
   * is riding along (or the tier is free). Non-null is what tells the card to
   * strike the list price.
   */
  offer: PriceDisplay | null;
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
}: PricingCardPriceInput): PricingCardPrice {
  const offer = usePricingModalStore((s) => s.offer);
  return {
    list: getPriceDisplay(price, originalPrice, durationIsMonth),
    offer:
      offer && price > 0
        ? getPriceDisplay(
            getOfferPrice(price, offer),
            originalPrice,
            durationIsMonth,
          )
        : null,
  };
}
