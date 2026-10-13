"use client";

import { Button } from "@heroui/button";
import {
  CancelIcon,
  Copy01Icon,
  GiftIcon,
  Share08Icon,
  Tick02Icon,
} from "@icons";
import { track } from "@/lib/analytics";
import { useShareLink } from "../hooks/useShareLink";
import { REFERRAL_COPY, REFERRAL_UI_COPY } from "../referralCopy";
import type { ReferralCopyVariant } from "../types/contract";
import type { OfferPrices } from "../utils/offerPrices";

interface PostPaymentShareCardProps {
  url: string;
  prices: OfferPrices;
  copyVariant: ReferralCopyVariant;
  onDismiss: () => void;
}

/** Under the payment receipt: one quiet line, the gift, one way to send it. */
export function PostPaymentShareCard({
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

  const dismiss = () => {
    track("referral:card_dismissed", {
      surface: "post_payment",
      copy_variant: copyVariant,
    });
    onDismiss();
  };

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
      <Button
        variant="flat"
        radius="full"
        fullWidth
        className="font-medium"
        startContent={shareIcon}
        onPress={canShareNatively ? shareNatively : copy}
      >
        {canShareNatively
          ? postPayment.cta
          : copied
            ? REFERRAL_UI_COPY.copied
            : REFERRAL_UI_COPY.copyLink}
      </Button>
    </section>
  );
}
