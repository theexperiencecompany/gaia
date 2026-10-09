"use client";

import { Chip } from "@heroui/chip";
import { Tab, Tabs } from "@heroui/tabs";
import type { Plan } from "../api/pricingApi";
import {
  type AnnualSavings,
  useAnnualSavings,
} from "../hooks/useAnnualSavings";

interface BillingPeriodTabsProps {
  isYearly: boolean;
  onChange: (isYearly: boolean) => void;
  /** Server-fetched plans, so the chip renders with the page. */
  initialPlans?: Plan[];
}

/** "2 months free" reads as a gift; "Save 17%" reads as a sum. Falls back to
 * the percentage only when the discount is too small to be a whole month. */
function annualSavingsLabel({ percent, monthsFree }: AnnualSavings): string {
  if (monthsFree < 1) return `Save ${percent}%`;
  return monthsFree === 1 ? "1 month free" : `${monthsFree} months free`;
}

/**
 * Monthly / Yearly switch for the pricing cards. The savings chip is derived
 * from the live plan prices — a hardcoded percentage shipped wrong once.
 */
export function BillingPeriodTabs({
  isYearly,
  onChange,
  initialPlans,
}: BillingPeriodTabsProps) {
  const savings = useAnnualSavings({ initialPlans });

  return (
    <Tabs
      selectedKey={isYearly ? "yearly" : "monthly"}
      onSelectionChange={(key) => onChange(key === "yearly")}
      radius="full"
      size="lg"
      aria-label="Billing period"
    >
      <Tab key="monthly" title="Monthly" />
      <Tab
        key="yearly"
        title={
          <div className="flex items-center gap-2">
            Yearly
            {savings !== null && (
              <Chip color="primary" size="sm" variant="solid">
                {annualSavingsLabel(savings)}
              </Chip>
            )}
          </div>
        }
      />
    </Tabs>
  );
}
