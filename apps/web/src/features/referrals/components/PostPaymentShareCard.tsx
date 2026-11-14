"use client";

import { Button } from "@heroui/button";
import {
  CancelIcon,
  Copy01Icon,
  GiftIcon,
  Share08Icon,
  Tick02Icon,
} from "@icons";
import type { ReferralCopyVariant } from "@shared/api/generated";
import { useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { track } from "@/lib/analytics";
import { useReferralMe } from "../hooks/useReferrals";
import { useShareLink } from "../hooks/useShareLink";
import { REFERRAL_COPY, REFERRAL_UI_COPY } from "../referralCopy";
import { type OfferPrices, offerPrices } from "../utils/offerPrices";

interface PostPaymentShareCardProps {
  url: string;
  prices: OfferPrices;
  copyVariant: ReferralCopyVariant;
  /** Omitted where the surrounding flow owns moving on, so the card has no close button. */
  onDismiss?: () => void;
}

/** Chained after a confirmed payment; renders nothing until the new subscriber's link exists. */
export function PostPaymentReferral() {
  const state = useReferralMe();
  const [dismissed, setDismissed] = useState(false);
  if (dismissed || state.status !== "ready") return null;
  return (
    <PostPaymentShareCard
      url={state.me.share_link}
      prices={offerPrices(state.me.offer)}
      copyVariant={state.me.copy_variant}
      onDismiss={() => setDismissed(true)}
    />
  );
}

/** The onboarding step right after the first payment; the flow's own button moves on. */
export function OnboardingReferral() {
  const state = useReferralMe();
  if (state.status !== "ready") return null;
  return (
    <PostPaymentShareCard
      url={state.me.share_link}
      prices={offerPrices(state.me.offer)}
      copyVariant={state.me.copy_variant}
    />
  );
}

/** Under the payment receipt: one quiet line, the gift, one way to send it. */
function PostPaymentShareCard({
  url,
  prices,
  copyVariant,
  onDismiss,
}: PostPaymentShareCardProps) {
  const { postPayment, share } = REFERRAL_COPY[copyVariant];
  const { canShareNatively, copied, copy, shareNatively } = useShareLink({
    surface: "post_payment",
    copyVariant,
    url,
    text: share.text(prices),
    emailSubject: share.emailSubject,
  });

  const dismiss = onDismiss
    ? () => {
        track("referral:card_dismissed", {
          surface: "post_payment",
          copy_variant: copyVariant,
        });
        onDismiss();
      }
    : null;

  const shareIcon = canShareNatively ? (
    <Share08Icon width={16} height={16} />
  ) : copied ? (
    <Tick02Icon width={16} height={16} />
  ) : (
    <Copy01Icon width={16} height={16} />
  );

  return (
    <section className="relative flex flex-col gap-4 rounded-3xl bg-zinc-900/60 p-5 backdrop-blur-2xl">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-zinc-200">
          {postPayment.title}
        </h2>
        {dismiss && (
          <Button
            isIconOnly
            aria-label={REFERRAL_UI_COPY.maybeLater}
            variant="light"
            size="sm"
            radius="full"
            className="-mr-1.5 text-zinc-500"
            onPress={dismiss}
          >
            <CancelIcon width={14} height={14} />
          </Button>
        )}
      </div>
      <div className="flex items-center gap-3 rounded-2xl bg-zinc-800/70 p-4">
        <GiftIcon width={20} height={20} className="shrink-0 text-zinc-400" />
        <p className="text-sm text-zinc-400 tabular-nums">
          <span className="text-base font-medium text-zinc-100">
            {prices.intro}
            {REFERRAL_UI_COPY.perMonth}
          </span>{" "}
          {REFERRAL_UI_COPY.giftPeriod(prices)}
        </p>
      </div>
      {/* The same raised cyan as the receipt's own CTA: the one thing this card asks for. */}
      <RaisedButton
        color="#00bbff"
        className="w-full text-black!"
        onClick={canShareNatively ? shareNatively : copy}
      >
        {shareIcon}
        {canShareNatively
          ? postPayment.cta
          : copied
            ? REFERRAL_UI_COPY.copied
            : REFERRAL_UI_COPY.copyLink}
      </RaisedButton>
    </section>
  );
}
