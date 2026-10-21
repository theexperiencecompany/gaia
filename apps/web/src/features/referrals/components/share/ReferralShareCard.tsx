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
import { RaisedButton } from "@/components/ui/raised-button";
import { type ShareSurface, useShareLink } from "../../hooks/useShareLink";
import { REFERRAL_COPY, REFERRAL_UI_COPY } from "../../referralCopy";
import type { OfferPrices } from "../../utils/offerPrices";

/** glass floats over a page backdrop; chat follows the chat tool-card contract. */
const CARD_TONES = {
  glass: {
    outer: "rounded-3xl bg-zinc-900/60 p-5 backdrop-blur-2xl",
    inner: "rounded-2xl bg-zinc-800/70 p-4",
  },
  chat: {
    outer: "rounded-2xl bg-zinc-800 p-4",
    inner: "rounded-2xl bg-zinc-900 p-3",
  },
} as const;

interface ReferralShareCardProps {
  surface: ShareSurface;
  tone: keyof typeof CARD_TONES;
  copy: { title: string; cta: string };
  url: string;
  prices: OfferPrices;
  copyVariant: ReferralCopyVariant;
  /** Omitted where the surrounding flow owns moving on, so the card has no close button. */
  onDismiss?: () => void;
}

/** One quiet line, the gift, one way to send it. */
export function ReferralShareCard({
  surface,
  tone,
  copy: { title, cta },
  url,
  prices,
  copyVariant,
  onDismiss,
}: ReferralShareCardProps) {
  const { share } = REFERRAL_COPY[copyVariant];
  const { canShareNatively, copied, copy, shareNatively } = useShareLink({
    surface,
    copyVariant,
    url,
    text: share.text(prices),
    emailSubject: share.emailSubject,
  });
  const classes = CARD_TONES[tone];

  const shareIcon = canShareNatively ? (
    <Share08Icon width={16} height={16} />
  ) : copied ? (
    <Tick02Icon width={16} height={16} />
  ) : (
    <Copy01Icon width={16} height={16} />
  );

  return (
    <section className={`relative flex flex-col gap-4 ${classes.outer}`}>
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-medium text-zinc-200">{title}</h2>
        {onDismiss && (
          <Button
            isIconOnly
            aria-label={REFERRAL_UI_COPY.maybeLater}
            variant="light"
            size="sm"
            radius="full"
            className="-mr-1.5 text-zinc-500"
            onPress={onDismiss}
          >
            <CancelIcon width={14} height={14} />
          </Button>
        )}
      </div>
      <div className={`flex items-center gap-3 ${classes.inner}`}>
        <GiftIcon width={20} height={20} className="shrink-0 text-zinc-400" />
        <p className="text-sm text-zinc-400 tabular-nums">
          <span className="text-base font-medium text-zinc-100">
            {prices.intro}
            {REFERRAL_UI_COPY.perMonth}
          </span>{" "}
          {REFERRAL_UI_COPY.giftPeriod(prices)}
        </p>
      </div>
      {/* The raised cyan of GAIA's primary CTA: the one thing this card asks for. */}
      <RaisedButton
        color="#00bbff"
        className="w-full text-black!"
        onClick={canShareNatively ? shareNatively : copy}
      >
        {shareIcon}
        {canShareNatively
          ? cta
          : copied
            ? REFERRAL_UI_COPY.copied
            : REFERRAL_UI_COPY.copyLink}
      </RaisedButton>
    </section>
  );
}
