"use client";

import type { ReceiptPrinterHeaderProps } from "@/features/pricing/components/receipt-printer.types";
import { cn } from "@/lib/utils";

export function ReceiptPrinterHeader({
  children,
  className,
  ...props
}: ReceiptPrinterHeaderProps) {
  return (
    <div
      className={cn(
        "relative z-10 flex h-8 items-start justify-between",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}
