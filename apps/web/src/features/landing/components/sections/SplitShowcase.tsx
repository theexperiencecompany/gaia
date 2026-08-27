import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import GetStartedButton from "../shared/GetStartedButton";

interface SplitShowcaseRow {
  icon: ReactNode;
  label: string;
}

interface SplitShowcaseProps {
  title: string;
  subtitle: string;
  rows: SplitShowcaseRow[];
  /** Put the visual tile before the copy on desktop. */
  reverse?: boolean;
  children: ReactNode;
}

/**
 * Landing split section: copy column (heading, one-liner, three hairline
 * rows, CTA) beside one square visual tile. Alternate `reverse` per
 * instance so consecutive sections mirror each other.
 */
export function SplitShowcase({
  title,
  subtitle,
  rows,
  reverse = false,
  children,
}: SplitShowcaseProps) {
  return (
    <section className="mx-auto grid w-full max-w-7xl grid-cols-1 items-center gap-12 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-2 lg:items-stretch lg:gap-20">
      <div className={reverse ? "lg:order-2" : undefined}>
        <h2 className="font-serif text-4xl font-medium sm:text-5xl">{title}</h2>
        <p className="mt-4 max-w-md text-base font-light leading-relaxed text-zinc-400 sm:text-lg">
          {subtitle}
        </p>

        <div className="mt-9 flex flex-col">
          {rows.map((row) => (
            <div
              key={row.label}
              className="flex items-center gap-3.5 border-b border-white/10 py-4 text-[15px] text-zinc-300 first:border-t"
            >
              <span className="text-zinc-500">{row.icon}</span>
              {row.label}
            </div>
          ))}
        </div>

        <div className="mt-9 flex justify-start">
          <GetStartedButton
            btnColor="#00bbff"
            classname="text-black! px-2 hover:scale-105"
            text="Get Started"
          />
        </div>
      </div>

      {/* On desktop the square tile is sized by the copy column's height
          (plus a little breathing room): the absolute wrapper opts it out of
          the grid row sizing, so the copy defines the row and the tile
          floats centered as a slightly larger square. The cap keeps every
          split section's tile the SAME size regardless of copy length. */}
      <div className={cn("relative", reverse && "lg:order-1")}>
        <div className="relative aspect-square w-full overflow-hidden rounded-3xl border border-white/10 lg:absolute lg:top-1/2 lg:left-1/2 lg:h-[calc(100%+5rem)] lg:w-auto lg:max-h-[500px] lg:max-w-[500px] lg:-translate-x-1/2 lg:-translate-y-1/2">
          {children}
        </div>
      </div>
    </section>
  );
}
