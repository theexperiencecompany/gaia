"use client";

import { useReducedMotion } from "motion/react";
import { useMemo } from "react";
import { ReceiptPrinterContext } from "@/features/pricing/components/receipt-printer/context";
import type { ReceiptPrinterRootProps } from "@/features/pricing/components/receipt-printer.types";
import { cn } from "@/lib/utils";

export function ReceiptPrinterRoot({
  "aria-label": ariaLabel = "Receipt printer",
  animate = true,
  children,
  className,
  feedMotion = "stepped",
  stage,
  ...props
}: ReceiptPrinterRootProps) {
  const shouldReduceMotion = useReducedMotion();
  const context = useMemo(
    () => ({
      animate,
      feedMotion,
      shouldMove: animate && !shouldReduceMotion,
      stage,
    }),
    [animate, feedMotion, shouldReduceMotion, stage],
  );

  return (
    <ReceiptPrinterContext.Provider value={context}>
      <section
        aria-label={ariaLabel}
        className={cn(
          "relative isolate flex w-full max-w-sm flex-col items-center",
          className,
        )}
        data-stage={stage}
        {...props}
      >
        {children}
      </section>
    </ReceiptPrinterContext.Provider>
  );
}
