"use client";

import { Chip } from "@heroui/chip";
import NumberFlow from "@number-flow/react";
import { TextMorph } from "torph/react";

import type { PriceDisplay } from "../utils/priceDisplay";

interface PricingCardPriceProps {
  list: PriceDisplay;
  /** Non-null when an offer applies — the list figures are then struck. */
  offer: PriceDisplay | null;
}

/**
 * NumberFlow pads its line box to 1.5em for the digit-roll mask, so the row is
 * pinned to that height and a plain-text headline (Enterprise's "Custom")
 * lands on the same baseline.
 */
export const PRICE_HEADLINE_ROW_CLASS = "flex min-h-18 items-baseline gap-2";

/** Headline price, billing sub-line and the annual savings chip. */
export function PricingCardPrice({ list, offer }: PricingCardPriceProps) {
  const { perMonthDollars, yearlyTotalDollars, priceSubLine, showSavings } =
    list;
  const offerPerMonthDollars = offer?.perMonthDollars ?? null;

  return (
    <div className="px-6 pb-5">
      <div className={PRICE_HEADLINE_ROW_CLASS}>
        {offerPerMonthDollars !== null && (
          <span className="text-2xl font-normal text-zinc-500 line-through">
            ${perMonthDollars.toLocaleString()}
          </span>
        )}
        <NumberFlow
          value={offerPerMonthDollars ?? perMonthDollars}
          format={{
            style: "currency",
            currency: "USD",
            maximumFractionDigits: 0,
          }}
          willChange
          className={`text-5xl font-semibold tracking-tight${
            offerPerMonthDollars !== null ? " text-success" : ""
          }`}
        />
        <span className="text-base font-normal text-zinc-400">/ month</span>
      </div>
      {/* Sub-line — morphs on the billing toggle to keep card heights aligned */}
      <div className="mt-1.5 flex min-h-6 items-center gap-2">
        <TextMorph
          as="span"
          className="text-sm font-normal text-zinc-400"
          ease={{ stiffness: 200, damping: 20 }}
        >
          {priceSubLine}
        </TextMorph>
        {!!yearlyTotalDollars && (
          <>
            <span aria-hidden className="size-1 rounded-full bg-zinc-600" />
            <YearlyTotal
              yearlyTotalDollars={yearlyTotalDollars}
              offerYearlyTotalDollars={offer?.yearlyTotalDollars ?? null}
            />
          </>
        )}
        {showSavings && (
          <Chip color="success" size="sm" variant="flat">
            <MonthsFree
              monthsFree={list.monthsFree}
              offerMonthsFree={offer?.monthsFree ?? null}
            />
          </Chip>
        )}
      </div>
    </div>
  );
}

interface YearlyTotalProps {
  yearlyTotalDollars: number;
  offerYearlyTotalDollars: number | null;
}

function YearlyTotal({
  yearlyTotalDollars,
  offerYearlyTotalDollars,
}: YearlyTotalProps) {
  if (offerYearlyTotalDollars === null)
    return (
      <span className="text-sm font-normal text-zinc-400">
        ${yearlyTotalDollars.toLocaleString()}
      </span>
    );
  return (
    <span className="flex items-center gap-1.5 text-sm font-normal">
      <span className="text-zinc-500 line-through">
        ${yearlyTotalDollars.toLocaleString()}
      </span>
      <span className="text-success">
        ${offerYearlyTotalDollars.toLocaleString()}
      </span>
    </span>
  );
}

interface MonthsFreeProps {
  monthsFree: number;
  offerMonthsFree: number | null;
}

function MonthsFree({ monthsFree, offerMonthsFree }: MonthsFreeProps) {
  if (offerMonthsFree === null) return `${monthsFree} months free`;
  return (
    <span className="flex items-center gap-1">
      <span className="line-through opacity-60">{monthsFree}</span>
      <span>{offerMonthsFree} months free</span>
    </span>
  );
}
