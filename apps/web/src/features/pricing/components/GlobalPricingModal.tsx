"use client";

import { usePricing } from "@/features/pricing/hooks/usePricing";
import { usePricingModalStore } from "@/stores/pricingModalStore";
import { PricingModal } from "./PricingModal";

export function GlobalPricingModal() {
  const { open, closeModal } = usePricingModalStore();
  const { plans } = usePricing();

  return <PricingModal isOpen={open} onClose={closeModal} plans={plans} />;
}
