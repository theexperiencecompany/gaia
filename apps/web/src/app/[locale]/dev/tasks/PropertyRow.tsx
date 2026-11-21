"use client";

import { Tooltip } from "@heroui/react";
import { InformationCircleIcon } from "@icons";
import type { ReactNode } from "react";

/** A fact about the task: its name on the left, its value on the right. */
export function PropertyRow({
  label,
  hint,
  children,
}: {
  label: string;
  /** What the property does, behind an info icon beside its name. */
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="grid min-h-9 grid-cols-[6.5rem_1fr] items-center">
      <span className="flex items-center gap-1 text-[13px] text-zinc-500">
        {label}
        {hint && (
          <Tooltip delay={200}>
            <Tooltip.Trigger
              aria-label={hint}
              render={(props) => <span {...props} className="flex" />}
            >
              <InformationCircleIcon className="size-3.5 text-zinc-600" />
            </Tooltip.Trigger>
            <Tooltip.Content placement="top" className="max-w-56">
              {hint}
            </Tooltip.Content>
          </Tooltip>
        )}
      </span>
      <div className="flex min-w-0 items-center">{children}</div>
    </div>
  );
}
