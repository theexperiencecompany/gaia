"use client";

import { Spinner } from "@heroui/spinner";
import { CheckmarkCircle02Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { easeOut } from "@/features/pricing/components/receipt-printer/context";
import type { ReceiptPrinterStage } from "@/features/pricing/components/receipt-printer.types";

/** Shared fade/scale motion for both indicator states. */
function fadeScaleMotion(animate: boolean, move: boolean) {
  return {
    animate: { opacity: 1, transform: "scale(1)" },
    exit: {
      opacity: animate ? 0 : 1,
      transform: move ? "scale(0.96)" : "scale(1)",
    },
    initial: {
      opacity: animate ? 0 : 1,
      transform: move ? "scale(0.94)" : "scale(1)",
    },
    transition: { duration: animate ? 0.16 : 0, ease: easeOut },
  } as const;
}

export function StatusIndicator({
  animate,
  move,
  stage,
}: {
  animate: boolean;
  move: boolean;
  stage: ReceiptPrinterStage;
}) {
  const motionProps = fadeScaleMotion(animate, move);

  return (
    <span
      aria-hidden="true"
      className="relative grid size-5 shrink-0 place-items-center"
    >
      <AnimatePresence initial={false} mode="sync">
        {stage === "complete" ? (
          <m.span
            {...motionProps}
            className="col-start-1 row-start-1 grid place-items-center text-emerald-400"
            key="complete"
          >
            <CheckmarkCircle02Icon className="size-[18px]" />
          </m.span>
        ) : (
          <m.span
            {...motionProps}
            className="col-start-1 row-start-1 grid place-items-center text-zinc-500"
            key="working"
          >
            <Spinner size="sm" variant="simple" />
          </m.span>
        )}
      </AnimatePresence>
    </span>
  );
}
