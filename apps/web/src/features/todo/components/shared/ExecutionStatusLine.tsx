"use client";

import Image from "next/image";
import type React from "react";
import { cn } from "@/lib/utils";
import type { ExecutionStatus } from "@/types/features/todoTypes";

// Plain sentences, not labels: the line must be understood cold, without
// learning a status vocabulary.
const STATUS: Record<ExecutionStatus, { label: string; className: string }> = {
  proposed: {
    label: "GAIA is waiting for your approval",
    className: "text-amber-400",
  },
  queued: { label: "GAIA will start on this soon", className: "text-blue-400" },
  running: {
    label: "GAIA is working on this right now",
    className: "text-blue-400",
  },
  needs_you: {
    label: "GAIA is waiting on your answer",
    className: "text-amber-400",
  },
  done: { label: "GAIA finished this", className: "text-emerald-400" },
  failed: { label: "GAIA couldn't finish this", className: "text-red-400" },
  expired: { label: "This offer expired", className: "text-zinc-500" },
  dismissed: { label: "You dismissed this", className: "text-zinc-500" },
};

/**
 * One sentence of lifecycle state for a GAIA todo's detail view. Hidden for
 * proposals — their decision card says it better.
 */
export const ExecutionStatusLine: React.FC<{
  status: ExecutionStatus | null | undefined;
}> = ({ status }) => {
  if (!status) return null;
  const { label, className } = STATUS[status];
  return (
    <div className="flex items-center gap-2 text-xs">
      <Image alt="GAIA" src="/images/logos/logo.webp" width={14} height={14} />
      <span className={cn("font-medium", className)}>{label}</span>
    </div>
  );
};
