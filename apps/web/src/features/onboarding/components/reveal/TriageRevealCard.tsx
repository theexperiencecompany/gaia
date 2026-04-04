"use client";

import { InboxUnreadIcon, Mail01Icon, MailOpenIcon } from "@icons";
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
      className="ml-10.75 overflow-hidden rounded-2xl bg-zinc-800/60 p-4 space-y-3"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 280, damping: 22 }}
    >
      {/* Stats */}
      <div className="flex gap-2">
        <div className="flex flex-1 items-center gap-2.5 rounded-xl bg-zinc-900 px-3 py-2.5">
          <Mail01Icon className="size-6 shrink-0 text-zinc-500" />
          <div>
            <p className="text-base font-semibold text-zinc-200 leading-none">
              {total_scanned.toLocaleString()}
            </p>
            <p className="mt-0.5 text-xs text-zinc-500">scanned</p>
          </div>
        </div>
        <div className="flex flex-1 items-center gap-2.5 rounded-xl bg-zinc-900 px-3 py-2.5">
          <InboxUnreadIcon className="size-6 shrink-0 text-zinc-500" />
          <div>
            <p className="text-base font-semibold text-zinc-200 leading-none">
              {total_unread.toLocaleString()}
            </p>
            <p className="mt-0.5 text-xs text-zinc-500">unread</p>
          </div>
        </div>
      </div>

      {/* Summary */}
      {summary && (
        <p className="text-sm leading-relaxed text-zinc-300">{summary}</p>
      )}

      {/* Patterns */}
      {patterns && patterns.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <MailOpenIcon className="size-3 text-zinc-600" />
            <p className="text-xs text-zinc-600">Patterns detected</p>
          </div>
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
        </div>
      )}
    </m.div>
  );
}
