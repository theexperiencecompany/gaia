"use client";

import type { ReceiptPrinterScreenProps } from "@/features/pricing/components/receipt-printer.types";
import { cn } from "@/lib/utils";

export function ReceiptPrinterScreen({
  children,
  className,
  style,
  ...props
}: ReceiptPrinterScreenProps) {
  return (
    <div
      className={cn(
        "relative z-10 isolate overflow-hidden bg-zinc-800 p-4 text-zinc-50 shadow-inner shadow-zinc-950/30 printer-screen",
        className,
      )}
      style={style}
      {...props}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-20 printer-screen-glow"
      />
      <div className="relative z-10">{children}</div>
    </div>
  );
}
