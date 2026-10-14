"use client";

import { useState } from "react";
import { track } from "@/lib/analytics";
import { useReferralMe } from "../hooks/useReferrals";
import { REFERRAL_COPY } from "../referralCopy";
import { offerPrices } from "../utils/offerPrices";
import { ReferralShareCard } from "./share/ReferralShareCard";

/** Chained after a confirmed payment; renders nothing until the new subscriber's link exists. */
export function PostPaymentReferral() {
  const state = useReferralMe();
  const [dismissed, setDismissed] = useState(false);
  if (dismissed || state.status !== "ready") return null;
  const { copy_variant: copyVariant } = state.me;

  const dismiss = () => {
    track("referral:card_dismissed", {
      surface: "post_payment",
      copy_variant: copyVariant,
    });
    setDismissed(true);
  };

  return (
    <ReferralShareCard
      surface="post_payment"
      tone="glass"
      copy={REFERRAL_COPY[copyVariant].postPayment}
      url={state.me.share_link}
      prices={offerPrices(state.me.offer)}
      copyVariant={copyVariant}
      onDismiss={dismiss}
    />
  );
}

/** The onboarding step right after the first payment; the flow's own button moves on. */
export function OnboardingReferral() {
  const state = useReferralMe();
  if (state.status !== "ready") return null;
  const { copy_variant: copyVariant } = state.me;
  return (
    <ReferralShareCard
      surface="post_payment"
      tone="glass"
      copy={REFERRAL_COPY[copyVariant].postPayment}
      url={state.me.share_link}
      prices={offerPrices(state.me.offer)}
      copyVariant={copyVariant}
    />
  );
}
