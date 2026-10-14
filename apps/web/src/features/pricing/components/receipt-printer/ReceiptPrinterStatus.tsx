"use client";

import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import {
  easeOut,
  useReceiptPrinter,
} from "@/features/pricing/components/receipt-printer/context";
import { StatusIndicator } from "@/features/pricing/components/receipt-printer/StatusIndicator";
import type {
  ReceiptPrinterStage,
  ReceiptPrinterStatusProps,
} from "@/features/pricing/components/receipt-printer.types";
import { cn } from "@/lib/utils";

const statusLabels: Record<ReceiptPrinterStage, string> = {
  processing: "Processing your order",
  printing: "Printing your receipt",
  complete: "Order complete",
};

export function ReceiptPrinterStatus({
  children,
  className,
  ...props
}: ReceiptPrinterStatusProps) {
  const { animate, shouldMove, stage } = useReceiptPrinter(
    "ReceiptPrinter.Status",
  );

  return (
    <div
      className={cn("flex min-w-0 items-center gap-2", className)}
      {...props}
    >
      <StatusIndicator animate={animate} move={shouldMove} stage={stage} />
      <div
        aria-live="polite"
        className="grid min-w-0 flex-1 items-center"
        role="status"
      >
        <AnimatePresence initial={false} mode="sync">
          <m.div
            animate={{ opacity: 1, transform: "translateY(0px)" }}
            className="col-start-1 row-start-1 truncate font-medium text-xs leading-none text-zinc-400"
            exit={{
              opacity: animate ? 0 : 1,
              transform: shouldMove ? "translateY(-4px)" : "translateY(0px)",
            }}
            initial={{
              opacity: animate ? 0 : 1,
              transform: shouldMove ? "translateY(4px)" : "translateY(0px)",
            }}
            key={stage}
            transition={{ duration: animate ? 0.18 : 0, ease: easeOut }}
          >
            {children ?? statusLabels[stage]}
          </m.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
