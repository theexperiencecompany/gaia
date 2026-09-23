"use client";

import type { ReceiptPrinterMachineProps } from "@/features/pricing/components/receipt-printer.types";
import { cn } from "@/lib/utils";

/* The machine is always the dark charcoal unit with the black LCD, in both
   themes — only its backdrop changes. Tailwind scans source text and cannot
   see template-literal interpolation inside arbitrary values, so the hex
   tones are inlined below rather than referenced via constants. */

const machineClassName =
  "relative isolate w-full overflow-hidden bg-zinc-900 pb-8 printer-machine [--printer-inner-radius:calc(var(--printer-radius)_-_var(--printer-inset))] [--printer-inset:0.75rem] [--printer-radius:1.5rem]";

export function ReceiptPrinterMachine({
  children,
  className,
  style,
  ...props
}: ReceiptPrinterMachineProps) {
  return (
    <div className={cn(machineClassName, className)} style={style} {...props}>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 z-0 bg-repeat opacity-30 mix-blend-multiply printer-noise"
      />
      {children}
      <div
        aria-hidden="true"
        className="absolute inset-x-6 bottom-[var(--printer-inset)] z-40 h-2 rounded-sm bg-zinc-950 shadow-inner shadow-zinc-950"
      />
    </div>
  );
}
