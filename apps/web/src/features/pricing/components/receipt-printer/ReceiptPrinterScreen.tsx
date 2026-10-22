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
        "relative z-10 isolate overflow-hidden bg-zinc-800 p-4 text-zinc-50 shadow-inner shadow-zinc-950/30 rounded-(--printer-inner-radius)",
        className,
      )}
      style={style}
      {...props}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-20 rounded-inherit shadow-[inset_0_0_24px_4px_color-mix(in_oklab,_#09090b_35%,_transparent)]"
      />
      <div className="relative z-10">{children}</div>
    </div>
  );
}
