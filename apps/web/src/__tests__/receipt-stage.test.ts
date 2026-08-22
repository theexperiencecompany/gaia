import { describe, expect, it } from "vitest";
import type { ReceiptPrinterStage } from "@/features/pricing/components/receipt-printer.types";
import {
  initialReceiptStageState,
  receiptStageReducer,
} from "@/features/pricing/hooks/useReceiptPrinterStage";

function advance(
  stage: ReceiptPrinterStage,
  event: Parameters<typeof receiptStageReducer>[1],
): ReceiptPrinterStage {
  return receiptStageReducer({ stage }, event).stage;
}

describe("receiptStageReducer", () => {
  it("starts at processing", () => {
    expect(initialReceiptStageState.stage).toBe("processing");
  });

  it("advances processing → printing on PAYMENT_CONFIRMED", () => {
    expect(advance("processing", "payment-confirmed")).toBe("printing");
  });

  it("ignores PAYMENT_CONFIRMED once printing", () => {
    // Duplicate webhook confirmations must not restart the feed.
    expect(advance("printing", "payment-confirmed")).toBe("printing");
    expect(advance("complete", "payment-confirmed")).toBe("complete");
  });

  it("advances printing → complete on PRINT_FINISHED", () => {
    expect(advance("printing", "print-finished")).toBe("complete");
  });

  it("ignores PRINT_FINISHED when not printing", () => {
    // The finish timer can only fire after the feed started; a stray event
    // (e.g. from a stale timer after unmount/remount) must not skip stages.
    expect(advance("processing", "print-finished")).toBe("processing");
    expect(advance("complete", "print-finished")).toBe("complete");
  });
});
