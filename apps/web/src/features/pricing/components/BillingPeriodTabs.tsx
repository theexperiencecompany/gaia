"use client";

import { Chip, Tabs } from "@heroui/react";
import { shapeVariants } from "@/components/shared/shape";
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
      className={shapeVariants({ shape: "pill" })}
      variant="primary"
      selectedKey={isYearly ? "yearly" : "monthly"}
      onSelectionChange={(key) => onChange(key === "yearly")}
      aria-label="Billing period"
    >
      <Tabs.ListContainer>
        <Tabs.List>
          <Tabs.Tab id="monthly">
            Monthly
            <Tabs.Indicator />
          </Tabs.Tab>
          <Tabs.Tab id="yearly">
            <div className="flex items-center gap-2">
              Yearly
              {savings !== null && (
                <Chip color="accent" size="sm" variant="primary">
                  {annualSavingsLabel(savings)}
                </Chip>
              )}
            </div>
            <Tabs.Indicator />
          </Tabs.Tab>
        </Tabs.List>
      </Tabs.ListContainer>
      <Tabs.Panel id="monthly">{null}</Tabs.Panel>
      <Tabs.Panel id="yearly">{null}</Tabs.Panel>
    </Tabs>
  );
}
