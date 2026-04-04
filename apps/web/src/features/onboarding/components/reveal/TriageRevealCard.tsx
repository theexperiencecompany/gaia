"use client";

import { m } from "motion/react";

interface TriageRevealCardProps {
  total_scanned: number;
  total_unread: number;
  summary?: string;
  patterns?: string[];
}

export function TriageRevealCard({
  total_scanned,
  total_unread,
  summary,
  patterns,
}: TriageRevealCardProps) {
  return (
    <m.div
      className="overflow-hidden rounded-2xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 280, damping: 22 }}
    >
      <p className="mb-1 text-xs text-zinc-500">
        Scanned {total_scanned} emails, {total_unread} unread
      </p>

      {summary && (
        <p className="mb-3 text-sm leading-relaxed text-zinc-300">{summary}</p>
      )}

      {patterns && patterns.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {patterns.map((pattern) => (
            <span
              key={pattern}
              className="rounded-full bg-zinc-700/60 px-2.5 py-0.5 text-xs text-zinc-400"
            >
              {pattern}
            </span>
          ))}
        </div>
      )}
    </m.div>
  );
}
