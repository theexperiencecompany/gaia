"use client";

import { Button } from "@heroui/react";
import { Skeleton } from "@heroui/react";

/** The cards a loading grid stands in for: Pro, then Enterprise beside it. */
const PLACEHOLDER_TIERS = ["pro", "enterprise"] as const;

export type PricingCardsFallbackState = "loading" | "error" | "empty";

interface PricingCardsFallbackProps {
  state: PricingCardsFallbackState;
  /** Mirrors PricingCards: without Enterprise the grid is one card wide. */
  hideEnterprise: boolean;
}

/** What stands in for the pricing grid until there are plans to show. */
export function PricingCardsFallback({
  state,
  hideEnterprise,
}: PricingCardsFallbackProps) {
  if (state === "loading") {
    // One placeholder per card the grid will show, stacked on a phone, so
    // nothing jumps when the plans land.
    const tiers = hideEnterprise
      ? PLACEHOLDER_TIERS.slice(0, 1)
      : PLACEHOLDER_TIERS;
    const grid =
      tiers.length === 1 ? "max-w-sm" : "max-w-sm sm:max-w-2xl sm:grid-cols-2";
    return (
      <div className={`mx-auto grid w-full grid-cols-1 gap-3 ${grid}`}>
        {tiers.map((tier) => (
          <Skeleton key={tier} className="h-[28rem] w-full rounded-2xl" />
        ))}
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="mx-auto flex w-full max-w-sm flex-col items-center gap-3 rounded-2xl bg-red-500/10 p-6 text-center">
        <p className="text-sm text-red-400">
          Unable to load pricing plans. Please refresh the page or try again
          later.
        </p>
        <Button
          variant="danger"
          onPress={() => window.location.reload()}
        >
          Refresh page
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-sm rounded-2xl bg-zinc-800 p-8 text-center">
      <p className="text-sm text-zinc-400">
        No pricing plans available at the moment.
      </p>
    </div>
  );
}
