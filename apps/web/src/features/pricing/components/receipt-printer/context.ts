import { createContext, useContext } from "react";
import type {
  ReceiptFeedMotion,
  ReceiptPrinterStage,
} from "@/features/pricing/components/receipt-printer.types";

export type ReceiptPrinterContextValue = {
  animate: boolean;
  feedMotion: ReceiptFeedMotion;
  shouldMove: boolean;
  stage: ReceiptPrinterStage;
};

export const ReceiptPrinterContext =
  createContext<ReceiptPrinterContextValue | null>(null);

export const easeOut = [0.23, 1, 0.32, 1] as const;
export const easeInOut = [0.77, 0, 0.175, 1] as const;

export function useReceiptPrinter(component: string) {
  const context = useContext(ReceiptPrinterContext);

  if (!context) {
    throw new Error(`${component} must be used inside ReceiptPrinter.Root.`);
  }

  return context;
}
