"use client";

import { ReceiptPrinterHeader } from "@/features/pricing/components/receipt-printer/ReceiptPrinterHeader";
import { ReceiptPrinterMachine } from "@/features/pricing/components/receipt-printer/ReceiptPrinterMachine";
import { ReceiptPrinterOutput } from "@/features/pricing/components/receipt-printer/ReceiptPrinterOutput";
import { ReceiptPrinterPaper } from "@/features/pricing/components/receipt-printer/ReceiptPrinterPaper";
import { ReceiptPrinterRoot } from "@/features/pricing/components/receipt-printer/ReceiptPrinterRoot";
import { ReceiptPrinterScreen } from "@/features/pricing/components/receipt-printer/ReceiptPrinterScreen";
import { ReceiptPrinterStatus } from "@/features/pricing/components/receipt-printer/ReceiptPrinterStatus";

// Object.assign keeps the export a real component (the Root) while hanging
// the composable parts off it — `<ReceiptPrinter.Root>` and friends read the
// same at every call site.
export const ReceiptPrinter = Object.assign(ReceiptPrinterRoot, {
  Header: ReceiptPrinterHeader,
  Machine: ReceiptPrinterMachine,
  Output: ReceiptPrinterOutput,
  Paper: ReceiptPrinterPaper,
  Root: ReceiptPrinterRoot,
  Screen: ReceiptPrinterScreen,
  Status: ReceiptPrinterStatus,
});
