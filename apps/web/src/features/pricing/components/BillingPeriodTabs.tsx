"use client";

import { Chip } from "@heroui/chip";
import { Tab, Tabs } from "@heroui/tabs";
import { useAnnualSavingsPercent } from "../hooks/useAnnualSavingsPercent";

interface BillingPeriodTabsProps {
  isYearly: boolean;
  onChange: (isYearly: boolean) => void;
}

/**
 * Monthly / Yearly switch for the pricing cards. The savings chip is derived
 * from the live plan prices — a hardcoded percentage shipped wrong once.
 */
const MONTHS_PER_YEAR = 12;

/** "2 months free" reads as a gift; "Save 17%" reads as a sum. Falls back to
 * the percentage only when the discount is too small to be a whole month. */
function annualSavingsLabel(savingsPercent: number): string {
  const monthsFree = Math.round((savingsPercent / 100) * MONTHS_PER_YEAR);
  if (monthsFree < 1) return `Save ${savingsPercent}%`;
  return monthsFree === 1 ? "1 month free" : `${monthsFree} months free`;
}

export function BillingPeriodTabs({
  isYearly,
  onChange,
}: BillingPeriodTabsProps) {
  const savingsPercent = useAnnualSavingsPercent();

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
            {savingsPercent !== null && (
              <Chip color="primary" size="sm" variant="solid">
                {annualSavingsLabel(savingsPercent)}
              </Chip>
            )}
          </div>
        }
      />
    </Tabs>
  );
}
