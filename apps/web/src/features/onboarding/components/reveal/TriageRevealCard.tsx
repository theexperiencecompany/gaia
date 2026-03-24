"use client";

import { m } from "motion/react";
import type { TriageResults } from "../../types/websocket";

const MAX_DISPLAY_EMAILS = 5;

type TriageRevealCardProps = TriageResults;

export function TriageRevealCard({
  total_scanned,
  total_unread,
  email_count,
  important_emails,
}: TriageRevealCardProps) {
  const displayedEmails = important_emails.slice(0, MAX_DISPLAY_EMAILS);
  const remainingCount = important_emails.length - displayedEmails.length;

  return (
    <m.div
      className="overflow-hidden rounded-2xl bg-zinc-800/60 p-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <p className="mb-3 text-xs text-zinc-400">
        {email_count != null && (
          <>
            Scanned{" "}
            <span className="font-medium text-zinc-300">{email_count}</span>{" "}
            emails &middot;{" "}
          </>
        )}
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
              className="flex flex-col gap-0.5"
            >
              <div className="flex items-baseline gap-1.5 text-xs">
                <span className="shrink-0 font-medium text-zinc-300 max-w-[120px] truncate">
                  {email.sender}
                </span>
                <span className="text-zinc-600">&mdash;</span>
                <span className="truncate text-zinc-400">{email.subject}</span>
              </div>
              {email.why_important && (
                <p className="pl-0.5 text-[11px] leading-tight text-zinc-500">
                  {email.why_important}
                </p>
              )}
            </div>
          ))}
          {remainingCount > 0 && (
            <p className="text-xs text-zinc-500">+ {remainingCount} more</p>
          )}
        </div>
      )}
    </m.div>
  );
}
