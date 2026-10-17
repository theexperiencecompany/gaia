"use client";

import { useChatCardNudge } from "../hooks/useChatCardNudge";
import { useReferralMe } from "../hooks/useReferrals";
import { REFERRAL_COPY } from "../referralCopy";
import { offerPrices } from "../utils/offerPrices";
import { ReferralShareCard } from "./share/ReferralShareCard";

/** Under a reply that just finished: shown only when the server grants this week's nudge. */
export function ChatReferralCard({ turnId }: Readonly<{ turnId: string }>) {
  const state = useReferralMe();
  const ready = state.status === "ready";
  const { show, dismiss } = useChatCardNudge(turnId, ready);
  if (!ready || !show) return null;
  const { copy_variant: copyVariant } = state.me;

  return (
    <div className="mt-2 mb-4 max-w-md pl-10">
      <ReferralShareCard
        surface="chat_card"
        tone="chat"
        copy={REFERRAL_COPY[copyVariant].chatCard}
        url={state.me.share_link}
        prices={offerPrices(state.me.offer)}
        copyVariant={copyVariant}
        onDismiss={dismiss}
      />
    </div>
  );
}
