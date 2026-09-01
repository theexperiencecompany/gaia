/**
 * `payment` stage — the exclusive one. Nothing but a single framing bubble
 * and the priced tiers is on screen here; the page hides the transcript for
 * this stage so the decision has no competition.
 *
 * There is no composer and no skip: the stage ends when the backend reports
 * an active subscription, which `useAwaitPaidStatus` polls for so a webhook
 * that lands after the checkout overlay closes still advances the flow.
 */

"use client";

import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { Tab, Tabs } from "@heroui/tabs";
import * as m from "motion/react-m";
import { useState } from "react";
import { PricingCards } from "@/features/pricing/components/PricingCards";
import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { PAYMENT_INTRO } from "../../constants/messages";
import { MOTION_FADE_UP } from "../../constants/motion";
import { useAwaitPaidStatus } from "../../hooks/useAwaitPaidStatus";
import { OnboardingBotBubble } from "../OnboardingMessages";

export function Payment() {
  const [isYearly, setIsYearly] = useState(false);
  const { isUnknown } = useIsPaid();
  useAwaitPaidStatus();

  return (
    <m.div className="flex flex-col items-center gap-6" {...MOTION_FADE_UP}>
      <div className="w-full">
        <OnboardingBotBubble text={PAYMENT_INTRO} />
      </div>

      {/* Never render the cards off an unresolved plan status: a paying user
          would be shown an upgrade prompt they already bought. */}
      {isUnknown ? (
        <Spinner size="lg" aria-label="Checking your subscription" />
      ) : (
        <>
          <Tabs
            selectedKey={isYearly ? "yearly" : "monthly"}
            onSelectionChange={(key) => setIsYearly(key === "yearly")}
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
                  <Chip color="primary" size="sm" variant="solid">
                    Save 25%
                  </Chip>
                </div>
              }
            />
          </Tabs>
          <PricingCards durationIsMonth={!isYearly} hideEnterprise />
        </>
      )}
    </m.div>
  );
}
