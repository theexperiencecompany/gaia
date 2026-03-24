"use client";

import { Mail01Icon } from "@icons";
import { m } from "motion/react";
import type { InboxScanResults } from "../../types/websocket";

type InboxRevealCardProps = InboxScanResults;

export function InboxRevealCard({ email_count }: InboxRevealCardProps) {
  return (
    <m.div
      className="flex items-center gap-3 rounded-2xl bg-zinc-800/60 px-4 py-3"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <Mail01Icon className="size-4 shrink-0 text-zinc-400" />
      <span className="text-sm text-zinc-300">
        Scanned <span className="font-medium text-white">{email_count}</span>{" "}
        emails
      </span>
    </m.div>
  );
}
