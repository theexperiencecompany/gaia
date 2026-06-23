"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface WorkflowSectionProps {
  label?: string;
  /** Optional one-line helper under the label */
  description?: string;
  /** Right-aligned action (e.g. an AI generate button) */
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * Consistent labeled section used throughout the workflow modal so every
 * block — instructions, trigger, options — shares the same header rhythm,
 * typography, and spacing.
 */
export default function WorkflowSection({
  label,
  description,
  action,
  children,
  className,
}: WorkflowSectionProps) {
  return (
    <section className={cn("space-y-2", className)}>
      {(label || action) && (
        <div className="flex min-h-7 items-center justify-between gap-2">
          {label ? (
            <h3 className="text-sm font-medium text-zinc-200">{label}</h3>
          ) : (
            <span />
          )}
          {action}
        </div>
      )}
      {description && <p className="text-xs text-zinc-500">{description}</p>}
      {children}
    </section>
  );
}
