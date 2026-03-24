"use client";

import { m } from "motion/react";
import type { WritingStyleResults } from "../../types/websocket";

type WritingStyleRevealCardProps = WritingStyleResults;

export function WritingStyleRevealCard({
  style_summary,
}: WritingStyleRevealCardProps) {
  return (
    <m.div
      className="rounded-xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <p className="mb-2 text-xs text-zinc-400">Your writing style</p>
      <p className="border-l-2 border-zinc-600 pl-3 text-sm text-zinc-400">
        {style_summary}
      </p>
    </m.div>
  );
}
