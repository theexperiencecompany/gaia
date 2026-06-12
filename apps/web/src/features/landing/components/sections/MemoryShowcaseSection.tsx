"use client";

import type { ComponentType } from "react";

import MemoryFoldersCard from "../demo/memory-bento/MemoryFoldersCard";
import MemoryJournalCard from "../demo/memory-bento/MemoryJournalCard";
import MemoryRecallCard from "../demo/memory-bento/MemoryRecallCard";
import LargeHeader from "../shared/LargeHeader";

interface BentoCard {
  title: string;
  description: string;
  Visual: ComponentType;
}

const BENTO_CARDS: BentoCard[] = [
  {
    title: "Mention it once, it's filed forever",
    description:
      "Your people, your places, your preferences. Every detail you drop in conversation gets organized into folders you can browse anytime.",
    Visual: MemoryFoldersCard,
  },
  {
    title: "It connects the dots for you",
    description:
      "Ask for a dinner spot and GAIA already knows your partner is vegetarian. You never explain yourself twice.",
    Visual: MemoryRecallCard,
  },
  {
    title: "A journal that holds you to it",
    description:
      "GAIA keeps a dated journal of your days, including what you promised, and follows up before deadlines slip.",
    Visual: MemoryJournalCard,
  },
];

export default function MemoryShowcaseSection() {
  return (
    <section className="flex flex-col items-center px-4 py-24 sm:px-6 sm:py-32 lg:px-8">
      <div className="flex w-full max-w-6xl flex-col items-center gap-10">
        <LargeHeader
          chipText="Memory"
          headingText="An assistant that actually knows you"
          subHeadingText='No "remember this." No setup. GAIA picks things up from conversation and brings the right context the next time it matters.'
          centered
        />

        <div className="grid w-full gap-4 md:grid-cols-3">
          {BENTO_CARDS.map(({ title, description, Visual }) => (
            <div
              key={title}
              className="flex flex-col gap-4 rounded-2xl bg-zinc-800 p-4 text-left"
            >
              <div className="flex-1">
                <Visual />
              </div>
              <div>
                <h3 className="text-base font-medium text-zinc-100">{title}</h3>
                <p className="mt-1 text-sm leading-relaxed text-zinc-400">
                  {description}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
