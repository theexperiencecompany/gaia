"use client";

import * as m from "motion/react-m";
import {
  easeInOut,
  easeOut,
  useReceiptPrinter,
} from "@/features/pricing/components/receipt-printer/context";
import type {
  ReceiptPrinterOutputProps,
  ReceiptPrinterStage,
} from "@/features/pricing/components/receipt-printer.types";
import { cn } from "@/lib/utils";

const printingTransformKeyframes = [
  "translateY(calc(-100% + 2px))",
  "translateY(-91%)",
  "translateY(-91%)",
  "translateY(-81%)",
  "translateY(-81%)",
  "translateY(-70%)",
  "translateY(-70%)",
  "translateY(-58%)",
  "translateY(-58%)",
  "translateY(-45%)",
  "translateY(-45%)",
  "translateY(-32%)",
  "translateY(-32%)",
  "translateY(-20%)",
  "translateY(-20%)",
  "translateY(-10%)",
  "translateY(-10%)",
  "translateY(-3%)",
  "translateY(-3%)",
  "translateY(0%)",
];

const printingKeyframeTimes = [
  0, 0.075, 0.105, 0.18, 0.21, 0.285, 0.315, 0.39, 0.42, 0.495, 0.525, 0.6,
  0.63, 0.705, 0.735, 0.81, 0.84, 0.915, 0.945, 1,
];

/** The paper's transform for the current stage/motion combination. */
function feedTransform(
  stage: ReceiptPrinterStage,
  shouldMove: boolean,
  stepped: boolean,
): string | string[] {
  if (stage === "printing" && shouldMove) {
    return stepped ? printingTransformKeyframes : "translateY(0%)";
  }
  if (stage !== "processing" || !shouldMove) return "translateY(0%)";
  return "translateY(calc(-100% + 2px))";
}

export function ReceiptPrinterOutput({
  children,
  className,
  ...props
}: ReceiptPrinterOutputProps) {
  const { animate, feedMotion, shouldMove, stage } = useReceiptPrinter(
    "ReceiptPrinter.Output",
  );
  const isReceiptVisible = stage !== "processing";
  const shouldUseSteppedFeed =
    feedMotion === "stepped" && stage === "printing" && shouldMove;

  return (
    <div
      className={cn(
        // Height follows the paper: a fixed track left a band of empty space
        // under short receipts. overflow-hidden still clips the feed-in.
        "relative z-50 -mt-4 max-h-[32rem] w-[calc(80%+3rem)] max-w-full overflow-hidden px-6",
        className,
      )}
      {...props}
    >
      {isReceiptVisible ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-6 -top-1 z-20 h-2 bg-zinc-950/75 blur-[6px]"
        />
      ) : null}

      <m.div
        animate={{
          opacity: isReceiptVisible ? 1 : 0,
          transform: feedTransform(stage, shouldMove, shouldUseSteppedFeed),
        }}
        aria-hidden={stage !== "complete"}
        className="relative isolate before:pointer-events-none before:absolute before:inset-x-3 before:top-3 before:bottom-4 before:z-0 before:rounded-sm before:shadow-[0_8px_24px_color-mix(in_oklab,#09090b_24%,transparent)] before:content-[''] after:pointer-events-none after:absolute after:right-[8%] after:bottom-0 after:left-[8%] after:z-0 after:h-3 after:translate-y-1.5 after:rounded-full after:bg-zinc-950/10 after:blur-lg after:content-['']"
        initial={false}
        transition={{
          opacity: { duration: animate ? 0.16 : 0, ease: easeOut },
          transform: {
            duration: shouldMove ? 1.75 : 0,
            ease: shouldUseSteppedFeed ? "linear" : easeInOut,
            times: shouldUseSteppedFeed ? printingKeyframeTimes : undefined,
          },
        }}
      >
        {children}
      </m.div>
    </div>
  );
}
