"use client";

import type { PlanDuration } from "@shared/api/generated";
import * as m from "motion/react-m";
import { MOTION_FADE_UP } from "@/features/onboarding/constants/motion";
import { PriceDock } from "./PriceDock";
import { ValueHeadline } from "./ValueHeadline";

interface SkippedPriceProps {
  headline: string;
  line: string;
  keepLabel: string;
  onCheckout: (period: PlanDuration) => void;
}

/** The price for someone who declined the live run: the promise without the proof. */
export function SkippedPrice({
  headline,
  line,
  keepLabel,
  onCheckout,
}: SkippedPriceProps) {
  return (
    <m.div
      className="flex flex-1 flex-col justify-center gap-8 @max-md:justify-start @max-md:pt-6"
      {...MOTION_FADE_UP}
    >
      <ValueHeadline headline={headline} line={line} />
      <PriceDock keepLabel={keepLabel} onCheckout={onCheckout} />
    </m.div>
  );
}
