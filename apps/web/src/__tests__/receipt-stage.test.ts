import { describe, expect, it } from "vitest";
import type { ReceiptPrinterStage } from "@/features/pricing/components/ReceiptPrinter";
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
    expect(advance("processing", { type: "PAYMENT_CONFIRMED" })).toBe(
      "printing",
    );
  });

  it("ignores PAYMENT_CONFIRMED once printing", () => {
    // Duplicate webhook confirmations must not restart the feed.
    expect(advance("printing", { type: "PAYMENT_CONFIRMED" })).toBe("printing");
    expect(advance("complete", { type: "PAYMENT_CONFIRMED" })).toBe("complete");
  });

  it("advances printing → complete on PRINT_FINISHED", () => {
    expect(advance("printing", { type: "PRINT_FINISHED" })).toBe("complete");
  });

  it("ignores PRINT_FINISHED when not printing", () => {
    // The finish timer can only fire after the feed started; a stray event
    // (e.g. from a stale timer after unmount/remount) must not skip stages.
    expect(advance("processing", { type: "PRINT_FINISHED" })).toBe(
      "processing",
    );
    expect(advance("complete", { type: "PRINT_FINISHED" })).toBe("complete");
  });
});
