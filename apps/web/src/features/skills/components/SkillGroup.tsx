"use client";

import type { ReactNode } from "react";
import { useState } from "react";
import { ChevronRight } from "@/components/shared/icons";
import { cn } from "@/lib/utils";

interface SkillGroupProps {
  /** Prominent leading glyph (integration logo or agent icon). */
  icon: ReactNode;
  label: string;
  count: number;
  /** Greyed out — e.g. a built-in group whose integration isn't connected. */
  deactivated?: boolean;
  defaultOpen?: boolean;
  /** Trailing header content (e.g. a status chip + Connect button). */
  trailing?: ReactNode;
  children: ReactNode;
}

/**
 * A collapsible folder grouping skills under an agent — folders are agents,
 * files are skills. The leading icon is a prominent tile so each group reads
 * at a glance.
 */
export function SkillGroup({
  icon,
  label,
  count,
  deactivated = false,
  defaultOpen = true,
  trailing,
  children,
}: SkillGroupProps) {
  const [open, setOpen] = useState(defaultOpen);
  const toggle = () => setOpen((v) => !v);

  return (
    <div className="overflow-hidden rounded-2xl bg-zinc-900/60">
      <div className="relative flex items-center gap-2 px-3 py-2.5 transition-colors hover:bg-white/5">
        {/* Full-row toggle: the whole padded header is the touch target. */}
        <button
          type="button"
          onClick={toggle}
          aria-label={`${open ? "Collapse" : "Expand"} ${label}`}
          aria-expanded={open}
          className="absolute inset-0 cursor-pointer"
        />
        <div
          className={cn(
            "pointer-events-none flex min-w-0 flex-1 items-center gap-3",
            deactivated && "opacity-60",
          )}
        >
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-zinc-800">
            {icon}
          </div>
          <span className="truncate text-sm font-medium text-zinc-100">
            {label}
          </span>
          <span className="shrink-0 text-xs text-zinc-500">{count}</span>
        </div>
        {/* Interactive actions sit above the overlay so they stay clickable. */}
        {trailing && <div className="relative z-10 shrink-0">{trailing}</div>}
        <ChevronRight
          className={cn(
            "pointer-events-none relative size-4 shrink-0 text-zinc-500 transition-transform",
            open && "rotate-90",
          )}
        />
      </div>
      {open && (
        <div className="divide-y divide-zinc-800/60 pb-1">{children}</div>
      )}
    </div>
  );
}
