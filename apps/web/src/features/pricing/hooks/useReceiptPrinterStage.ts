"use client";

import { useEffect, useReducer } from "react";
import type { ReceiptPrinterStage } from "@/features/pricing/components/ReceiptPrinter";

/**
 * How long the paper feed animation runs before the printer reports
 * "complete". Matches the 1.75s stepped-feed transition plus a beat of
 * settle time so the receipt comes to rest before the check appears.
 */
export const PRINT_FEED_DURATION_MS = 2_200;

export type ReceiptStageState = {
  stage: ReceiptPrinterStage;
};

export type ReceiptStageEvent =
  | { type: "PAYMENT_CONFIRMED" }
  | { type: "PRINT_FINISHED" };

export const initialReceiptStageState: ReceiptStageState = {
  stage: "processing",
};

export function receiptStageReducer(
  state: ReceiptStageState,
  event: ReceiptStageEvent,
): ReceiptStageState {
  switch (event.type) {
    case "PAYMENT_CONFIRMED":
      // Idempotent: confirmation can only advance processing → printing.
      return state.stage === "processing" ? { stage: "printing" } : state;
    case "PRINT_FINISHED":
      return state.stage === "printing" ? { stage: "complete" } : state;
  }
}

/**
 * Drives the receipt-printer stages for the post-payment screen:
 * "processing" while the payment webhook is being verified, then
 * "printing" once confirmation lands, then "complete" after the paper
 * feed animation has finished.
 */
export function useReceiptPrinterStage(
  paymentConfirmed: boolean,
): ReceiptPrinterStage {
  const [state, dispatch] = useReducer(
    receiptStageReducer,
    initialReceiptStageState,
  );

  useEffect(() => {
    if (paymentConfirmed) {
      dispatch({ type: "PAYMENT_CONFIRMED" });
    }
  }, [paymentConfirmed]);

  useEffect(() => {
    if (state.stage !== "printing") {
      return;
    }

    const timer = setTimeout(
      () => dispatch({ type: "PRINT_FINISHED" }),
      PRINT_FEED_DURATION_MS,
    );
    return () => clearTimeout(timer);
  }, [state.stage]);

  return state.stage;
}
