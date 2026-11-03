"use client";

import { Button } from "@heroui/button";
import type { PlanDuration } from "@shared/api/generated";
import { formatWholeOrCents } from "@/features/pricing/utils/money";
import {
  MONTHLY_PRICE_MINOR,
  PRICE_CURRENCY,
  YEARLY_PRICE_MINOR,
} from "../labData";
import { CheckoutDock } from "./CheckoutDock";

export const MONTHLY_PRICE_LABEL = formatWholeOrCents(
  MONTHLY_PRICE_MINOR,
  PRICE_CURRENCY,
);
const YEARLY_PRICE_LABEL = formatWholeOrCents(
  YEARLY_PRICE_MINOR,
  PRICE_CURRENCY,
);

interface PriceDockProps {
  /** What they keep by paying, e.g. "Keep this every morning". The price is appended. */
  keepLabel: string;
  onCheckout: (period: PlanDuration) => void;
}

/** Monthly as the one action, yearly as a quiet alternative. */
export function PriceDock({ keepLabel, onCheckout }: PriceDockProps) {
  return (
    <CheckoutDock
      label={`${keepLabel}, ${MONTHLY_PRICE_LABEL}/month`}
      onPress={() => onCheckout("monthly")}
    >
      <Button
        size="sm"
        variant="light"
        className="text-zinc-500"
        onPress={() => onCheckout("yearly")}
      >
        or {YEARLY_PRICE_LABEL} for the year
      </Button>
    </CheckoutDock>
  );
}
