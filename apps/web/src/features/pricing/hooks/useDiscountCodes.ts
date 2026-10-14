"use client";

import { useQuery } from "@tanstack/react-query";

import { pricingApi } from "../api/pricingApi";

/** The coupon codes the server advertises; a code is null when its setting is unset. */
export function useDiscountCodes() {
  return useQuery({
    queryKey: ["discount-codes"],
    queryFn: () => pricingApi.getDiscountCodes(),
    staleTime: 5 * 60 * 1000,
  });
}
