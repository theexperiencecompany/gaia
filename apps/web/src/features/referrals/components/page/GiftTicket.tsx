import { GiftIcon } from "@icons";
import type { CSSProperties, ReactNode } from "react";
import { REFERRAL_UI_COPY } from "../../referralCopy";
import type { OfferPrices } from "../../utils/offerPrices";
import { PriceTag } from "../PriceTag";
import { ReferralQrCode } from "../share/ReferralQrCode";

const NOTCH = "14px";

// Two half-masks, each punching a notch where the perforation meets an edge;
// --stub is the tear-off's width, set per breakpoint on the element.
const PERFORATION_MASK: CSSProperties = {
  maskImage: [
    `radial-gradient(circle at calc(100% - var(--stub)) 0, transparent ${NOTCH}, #000 calc(${NOTCH} + 0.5px))`,
    `radial-gradient(circle at calc(100% - var(--stub)) 100%, transparent ${NOTCH}, #000 calc(${NOTCH} + 0.5px))`,
  ].join(", "),
  maskSize: "100% 51%",
  maskPosition: "top, bottom",
  maskRepeat: "no-repeat",
};

const PERFORATION_LINE: CSSProperties = {
  backgroundImage:
    "linear-gradient(to bottom, rgb(113 113 122 / 0.55) 50%, transparent 50%)",
  backgroundSize: "1px 10px",
};

interface GiftTicketProps {
  prices: OfferPrices;
  url: string;
  /** Rendered under the price, e.g. the milestone bar. */
  footer?: ReactNode;
}

export function GiftTicket({ prices, url, footer }: GiftTicketProps) {
  return (
    <div
      className="relative flex rounded-3xl bg-zinc-800 [--stub:4.5rem] sm:[--stub:11rem]"
      style={PERFORATION_MASK}
    >
      <div className="flex min-w-0 flex-1 flex-col justify-between gap-8 p-6">
        <div className="flex flex-col gap-1.5">
          <PriceTag price={prices.intro} />
          <p className="text-sm text-zinc-400">
            {REFERRAL_UI_COPY.giftPeriod(prices)}
          </p>
        </div>
        {footer}
      </div>
      <div
        aria-hidden
        className="my-6 w-px shrink-0"
        style={PERFORATION_LINE}
      />
      <div className="flex w-(--stub) shrink-0 flex-col items-center justify-center gap-2 p-4">
        <div className="hidden flex-col items-center gap-2 sm:flex">
          <ReferralQrCode url={url} size={104} />
          <p className="text-center text-[11px] text-zinc-500">
            {REFERRAL_UI_COPY.qrHintShort}
          </p>
        </div>
        <GiftIcon className="text-zinc-600 sm:hidden" width={24} height={24} />
      </div>
    </div>
  );
}
