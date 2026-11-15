"use client";

import { Button } from "@heroui/button";
import { Copy01Icon, Share08Icon, Tick02Icon } from "@icons";
import type { ReferralCopyVariant } from "@shared/api/generated";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { cn } from "@/lib/utils";
import { type ShareSurface, useShareLink } from "../../hooks/useShareLink";
import { REFERRAL_COPY, REFERRAL_UI_COPY } from "../../referralCopy";
import type { OfferPrices } from "../../utils/offerPrices";
import { ShareChannels } from "./ShareChannels";

const ICON_SWAP = {
  initial: { opacity: 0, scale: 0.25, filter: "blur(4px)" },
  animate: { opacity: 1, scale: 1, filter: "blur(0px)" },
  exit: { opacity: 0, scale: 0.25, filter: "blur(4px)" },
  transition: { type: "spring", duration: 0.3, bounce: 0 },
} as const;

interface ShareLinkPanelProps {
  url: string;
  prices: OfferPrices;
  copyVariant: ReferralCopyVariant;
  surface: ShareSurface;
  className?: string;
}

const displayLink = (url: string) => url.replace(/^https?:\/\//, "");

export function ShareLinkPanel({
  url,
  prices,
  copyVariant,
  surface,
  className,
}: ShareLinkPanelProps) {
  const { share } = REFERRAL_COPY[copyVariant];
  const {
    canShareNatively,
    copied,
    copy,
    shareNatively,
    openChannel,
    recordQrOpened,
  } = useShareLink({
    surface,
    copyVariant,
    url,
    text: share.text(prices),
    emailSubject: share.emailSubject,
  });

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div className="flex items-center gap-2">
        {/* The whole link is the copy target: a click anywhere on it copies, like the label says. */}
        <Button
          variant="flat"
          radius="full"
          aria-label={
            copied ? REFERRAL_UI_COPY.copied : REFERRAL_UI_COPY.copyLink
          }
          className="h-11 min-w-0 flex-1 justify-between gap-3 pr-4 pl-5 font-normal"
          onPress={copy}
          endContent={
            <span className="flex shrink-0 items-center gap-1.5 text-sm font-medium text-zinc-300">
              <AnimatePresence initial={false} mode="popLayout">
                <m.span key={copied ? "done" : "copy"} {...ICON_SWAP}>
                  {copied ? (
                    <Tick02Icon width={16} height={16} />
                  ) : (
                    <Copy01Icon width={16} height={16} />
                  )}
                </m.span>
              </AnimatePresence>
              <span className="hidden sm:inline">
                {copied ? REFERRAL_UI_COPY.copied : REFERRAL_UI_COPY.copyLink}
              </span>
            </span>
          }
        >
          <span className="min-w-0 truncate text-sm text-zinc-200">
            {displayLink(url)}
          </span>
        </Button>
        {canShareNatively && (
          <Button
            color="primary"
            radius="full"
            className="h-11 shrink-0 gap-1.5 px-5 font-medium"
            onPress={shareNatively}
            startContent={<Share08Icon width={16} height={16} />}
          >
            {REFERRAL_UI_COPY.share}
          </Button>
        )}
      </div>
      <ShareChannels
        url={url}
        onChannel={openChannel}
        onQrOpened={recordQrOpened}
      />
    </div>
  );
}
