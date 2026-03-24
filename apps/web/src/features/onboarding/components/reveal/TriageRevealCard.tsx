"use client";

import { m } from "motion/react";
import type { TriageResults } from "../../types/websocket";

type TriageRevealCardProps = TriageResults;

export function TriageRevealCard({
  total_scanned,
  total_unread,
  important_emails,
}: TriageRevealCardProps) {
  const displayedEmails = important_emails.slice(0, 3);

  return (
    <m.div
      className="overflow-hidden rounded-2xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <p className="mb-3 text-xs text-zinc-400">
        Sorted{" "}
        <span className="font-medium text-zinc-300">{total_scanned}</span>{" "}
        emails,{" "}
        <span className="font-medium text-zinc-300">{total_unread}</span> unread
      </p>
      {displayedEmails.length > 0 && (
        <div className="flex flex-col gap-2">
          {displayedEmails.map((email, index) => (
            <div
              key={`${email.sender}-${index}`}
              className="flex items-baseline gap-1.5 text-xs"
            >
              <span className="shrink-0 font-medium text-zinc-300 max-w-[120px] truncate">
                {email.sender}
              </span>
              <span className="text-zinc-600">—</span>
              <span className="truncate text-zinc-400">{email.subject}</span>
            </div>
          ))}
        </div>
      )}
    </m.div>
  );
}
