"use client";

import { GiftIcon } from "@icons";

import { cn } from "@/lib/utils";

interface RewardTicketProps {
  /** Big value on the stub, e.g. "1 MONTH" or "$30". */
  value: string;
  /** Small line under the value, e.g. "OF GAIA PRO, FREE". */
  caption: string;
  /** Tiny eyebrow on the perforated counterfoil, e.g. "REWARD". */
  eyebrow?: string;
  className?: string;
}

// A dimensional, Airbnb-style gift-card "ticket" built entirely in CSS/SVG so it
// stays crisp at any size and on-brand for the dark theme. The notch + dashed
// perforation that separate the counterfoil from the main stub are drawn with a
// masked SVG edge rather than overlaid circles, so the cut reads cleanly against
// any background.
export function RewardTicket({
  value,
  caption,
  eyebrow = "Reward",
  className,
}: RewardTicketProps) {
  return (
    <div
      className={cn(
        "relative inline-flex select-none overflow-hidden rounded-3xl",
        "bg-gradient-to-br from-zinc-700 via-zinc-800 to-zinc-900",
        "shadow-[0_24px_60px_-20px_rgba(0,0,0,0.85)]",
        className,
      )}
    >
      {/* Subtle top sheen so the surface catches light like a physical card. */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-white/15" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-white/[0.04] to-transparent" />

      {/* Counterfoil — the perforated stub on the left. */}
      <div className="relative flex flex-col items-center justify-center gap-1 px-5 py-7">
        <div className="rounded-full bg-primary/15 p-2.5">
          <GiftIcon size={22} className="text-primary" />
        </div>
        <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">
          {eyebrow}
        </span>
      </div>

      {/* Perforation: a dashed vertical line with a half-circle notch top & bottom. */}
      <div className="relative flex items-center" aria-hidden="true">
        <div className="absolute -top-2 left-1/2 size-4 -translate-x-1/2 rounded-full bg-[#111111]" />
        <div className="absolute -bottom-2 left-1/2 size-4 -translate-x-1/2 rounded-full bg-[#111111]" />
        <div className="mx-px h-[70%] border-l border-dashed border-white/20" />
      </div>

      {/* Main stub — the headline value. */}
      <div className="flex flex-col justify-center px-7 py-7">
        <span className="font-serif text-3xl font-normal leading-none tracking-tight text-white">
          {value}
        </span>
        <span className="mt-2 text-[11px] font-medium uppercase tracking-[0.16em] text-zinc-400">
          {caption}
        </span>
      </div>
    </div>
  );
}
