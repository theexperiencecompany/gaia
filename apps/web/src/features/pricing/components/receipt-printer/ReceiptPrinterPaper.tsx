"use client";

import type { ReceiptPrinterPaperProps } from "@/features/pricing/components/receipt-printer.types";
import { cn } from "@/lib/utils";

const receiptToothCount = 40;
const receiptToothDepth = 4;
const receiptToothPoints = Array.from(
  { length: receiptToothCount * 2 },
  (_, index) => {
    const x = 100 - ((index + 1) * 100) / (receiptToothCount * 2);
    const y = index % 2 === 0 ? "100%" : `calc(100% - ${receiptToothDepth}px)`;

    return `${x}% ${y}`;
  },
).join(", ");
const receiptClipPath = `polygon(0 0, 100% 0, 100% calc(100% - ${receiptToothDepth}px), ${receiptToothPoints})`;

export function ReceiptPrinterPaper({
  children,
  className,
  style,
  ...props
}: ReceiptPrinterPaperProps) {
  return (
    <article
      className={cn(
        "relative z-10 min-h-80 bg-zinc-50 bg-[url('/textures/receipt-paper.svg')] bg-cover px-6 pt-7 pb-8 font-mono text-zinc-950 bg-blend-soft-light",
        className,
      )}
      style={{ clipPath: receiptClipPath, ...style }}
      {...props}
    >
      {children}
    </article>
  );
}
