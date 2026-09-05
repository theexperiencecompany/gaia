"use client";

import type { ReceiptPrinterScreenProps } from "@/features/pricing/components/receipt-printer.types";
import { cn } from "@/lib/utils";

export function ReceiptPrinterScreen({
  children,
  className,
  ...props
}: ReceiptPrinterScreenProps) {
  return (
    <div
      className={cn(
        "relative z-10 isolate overflow-hidden rounded-[var(--printer-inner-radius)] bg-zinc-800 p-4 text-zinc-50 shadow-inner shadow-zinc-950/30 after:pointer-events-none after:absolute after:inset-0 after:z-20 after:rounded-[inherit] after:shadow-[inset_0_0_24px_4px_color-mix(in_oklab,#09090b_35%,transparent)] after:content-['']",
        className,
      )}
      {...props}
    >
      <div className="relative z-10">{children}</div>
    </div>
  );
}
