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
                Save {savingsPercent}%
              </Chip>
            )}
          </div>
        }
      />
    </Tabs>
  );
}
