"use client";

import type { ReceiptPrinterMachineProps } from "@/features/pricing/components/receipt-printer.types";
import { cn } from "@/lib/utils";

/* The machine is always the dark charcoal unit with the black LCD, in both
   themes — only its backdrop changes. Tailwind scans source text and cannot
   see template-literal interpolation inside arbitrary values, so the hex
   tones are inlined below rather than referenced via constants. */

const machineClassName =
  "relative isolate w-full overflow-hidden rounded-[var(--printer-radius)] bg-zinc-900 p-[var(--printer-inset)] pb-8 shadow-[0_20px_36px_-20px_color-mix(in_oklab,#18181b_55%,transparent),0_6px_14px_-8px_color-mix(in_oklab,#18181b_24%,transparent),inset_0_1px_0_color-mix(in_oklab,#fafafa_10%,transparent),inset_0_-1px_0_color-mix(in_oklab,#18181b_55%,transparent)] [--printer-inner-radius:calc(var(--printer-radius)_-_var(--printer-inset))] [--printer-inset:0.75rem] [--printer-radius:1.5rem] before:pointer-events-none before:absolute before:inset-0 before:z-0 before:rounded-[inherit] before:bg-[url('/textures/plastic-noise.svg')] before:bg-[length:180px_180px] before:bg-repeat before:opacity-30 before:mix-blend-multiply before:content-['']";

export function ReceiptPrinterMachine({
  children,
  className,
  ...props
}: ReceiptPrinterMachineProps) {
  return (
    <div className={cn(machineClassName, className)} {...props}>
      {children}
      <div
        aria-hidden="true"
        className="absolute inset-x-6 bottom-[var(--printer-inset)] z-40 h-2 rounded-[0.25rem] bg-zinc-950 shadow-inner shadow-zinc-950"
      />
    </div>
  );
}
