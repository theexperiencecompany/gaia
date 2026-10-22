"use client";

import type { ReceiptPrinterMachineProps } from "@/features/pricing/components/receipt-printer.types";
import { cn } from "@/lib/utils";

/* The machine is always the dark charcoal unit with the black LCD, in both
   themes — only its backdrop changes. */

const machineClassName =
  "relative isolate w-full overflow-hidden rounded-(--printer-radius) bg-zinc-900 p-(--printer-inset) pb-8 shadow-[0_20px_36px_-20px_color-mix(in_oklab,_#18181b_55%,_transparent),_0_6px_14px_-8px_color-mix(in_oklab,_#18181b_24%,_transparent),_inset_0_1px_0_color-mix(in_oklab,_#fafafa_10%,_transparent),_inset_0_-1px_0_color-mix(in_oklab,_#18181b_55%,_transparent)] [--printer-inner-radius:calc(var(--printer-radius)_-_var(--printer-inset))] [--printer-inset:0.75rem] [--printer-radius:1.5rem]";

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
        className="pointer-events-none absolute inset-0 z-0 bg-repeat opacity-30 mix-blend-multiply rounded-inherit bg-[url('/textures/plastic-noise.svg')]"
      />
      {children}
      <div
        aria-hidden="true"
        className="absolute inset-x-6 bottom-[var(--printer-inset)] z-40 h-2 rounded-sm bg-zinc-950 shadow-inner shadow-zinc-950"
      />
    </div>
  );
}
