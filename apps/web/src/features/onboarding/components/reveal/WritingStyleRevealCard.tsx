"use client";

import { m } from "motion/react";
import { WRITING_STYLE_LABEL } from "../../constants/messages";
import type { WritingStyleResults } from "../../types/websocket";

type WritingStyleRevealCardProps = WritingStyleResults;

export function WritingStyleRevealCard({
  style_summary,
}: WritingStyleRevealCardProps) {
  return (
    <m.div
      className="overflow-hidden rounded-2xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 280, damping: 22 }}
    >
      <p className="mb-2 text-xs text-zinc-400">{WRITING_STYLE_LABEL}</p>
      <m.p
        className="pl-3 text-sm text-zinc-400"
        initial={{ opacity: 0, x: -6 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.06, duration: 0.25, ease: [0.19, 1, 0.22, 1] }}
      >
        {style_summary}
      </m.p>
    </m.div>
  );
}
