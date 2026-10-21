"use client";

import {
  CheckmarkCircle02Icon,
  CircleArrowRight02Icon,
  Copy01Icon,
} from "@icons";

import { RaisedButton } from "@/components/ui/raised-button";
import { useAnnualSavings } from "@/features/pricing/hooks/useAnnualSavings";

import {
  DISCOUNT_PERCENT,
  DISCOUNT_TERMS,
  discountYearlyNote,
  INK,
  OFFER_LEAD,
} from "./content";

/** The offer button reads as ink on paper: RaisedButton's flat black treatment. */
const CTA_BLACK = "#000000";

interface LetterOfferProps {
  discountCode: string;
  copied: boolean;
  onCopyCode: () => void;
  onClaim: () => void;
}

/** The offer, seamless and inline, while the code still works. */
export function LetterOffer({
  discountCode,
  copied,
  onCopyCode,
  onClaim,
}: LetterOfferProps) {
  // Only said once the live prices are known, so the months are never a guess.
  const monthsFree =
    useAnnualSavings({ offerPercent: DISCOUNT_PERCENT })?.monthsFree ?? 0;
  const yearlyNote = monthsFree > 0 ? discountYearlyNote(monthsFree) : null;

  return (
    <div className="mt-3 space-y-2">
      <p
        style={{
          fontSize: "var(--letter-body)",
          lineHeight: "var(--letter-body-lh)",
        }}
      >
        {OFFER_LEAD} Take{" "}
        <strong className="font-bold">{DISCOUNT_PERCENT}% off</strong> with{" "}
        <button
          type="button"
          onClick={onCopyCode}
          aria-label={`Copy the discount code ${discountCode}`}
          title={copied ? "Copied" : "Copy code"}
          className="mx-0.5 inline-flex translate-y-[-1px] cursor-pointer items-center gap-1 rounded px-1 align-middle font-bold outline-none transition-colors hover:bg-black/10 focus-visible:ring-2 focus-visible:ring-black/60 active:scale-95"
          style={{ color: INK }}
        >
          {discountCode}
          {copied ? (
            <CheckmarkCircle02Icon className="h-3.5 w-3.5" />
          ) : (
            <Copy01Icon className="h-3 w-3" />
          )}
        </button>
        at checkout.{yearlyNote && ` ${yearlyNote}`}
      </p>
      <RaisedButton
        color={CTA_BLACK}
        size="sm"
        className="mt-1 px-4 font-semibold"
        onClick={onClaim}
      >
        Claim {DISCOUNT_PERCENT}% off
        <CircleArrowRight02Icon className="h-4 w-4" />
      </RaisedButton>
      <p
        className="opacity-60"
        style={{ fontSize: "calc(var(--letter-small) * 0.92)" }}
      >
        {DISCOUNT_TERMS}
      </p>
    </div>
  );
}
