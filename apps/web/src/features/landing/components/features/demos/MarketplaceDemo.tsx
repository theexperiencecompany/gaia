"use client";

import { m, useInView } from "motion/react";
import { useRef } from "react";

interface MarketplaceCard {
  name: string;
  creator: string;
  clones: string;
  category: string;
}

const CARDS: MarketplaceCard[] = [
  {
    name: "Airtable Sync",
    creator: "@mkaye",
    clones: "342",
    category: "Productivity",
  },
  {
    name: "Linear Standup Bot",
    creator: "@devtools_co",
    clones: "891",
    category: "Automation",
  },
  {
    name: "Stripe Revenue Digest",
    creator: "@revops_labs",
    clones: "1.2k",
    category: "Finance",
  },
];

export default function MarketplaceDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true });

  return (
    <div ref={ref} className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {CARDS.map((card, index) => (
        <m.div
          key={card.name}
          initial={{ opacity: 0, y: 16 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 16 }}
          transition={{ duration: 0.4, delay: index * 0.12, ease: "easeOut" }}
          className="rounded-2xl bg-zinc-800 p-4 flex flex-col gap-3"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium text-zinc-100">
              {card.name}
            </span>
            <span className="rounded-full bg-zinc-700 px-2 py-0.5 text-xs text-zinc-400 shrink-0">
              {card.category}
            </span>
          </div>
          <p className="text-xs text-zinc-500">{card.creator}</p>
          <p className="text-xs text-zinc-400">↗ {card.clones} clones</p>
          <button
            type="button"
            className="rounded-lg bg-[#00bbff]/10 text-[#00bbff] text-xs px-3 py-1 w-fit"
          >
            Install
          </button>
        </m.div>
      ))}
    </div>
  );
}
