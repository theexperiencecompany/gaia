/**
 * Compact card shown above the run-now chat stream summarising the todo the
 * user chose to execute, plus the source email it was derived from (if any).
 * Lives in its own file so RevealTodos.tsx stays within the components-per-file
 * limit.
 */

"use client";

import { Chip } from "@heroui/chip";
import { CheckmarkCircle02Icon, Mail01Icon } from "@icons";

export interface SelectedTodoIndicatorProps {
  title: string;
  sourceEmail: { sender: string; subject: string } | null;
}

export function SelectedTodoIndicator({
  title,
  sourceEmail,
}: SelectedTodoIndicatorProps) {
  return (
    <div className="rounded-2xl bg-zinc-900 p-3">
      <Chip
        color="success"
        variant="flat"
        size="sm"
        startContent={<CheckmarkCircle02Icon className="size-3.5" />}
      >
        Selected todo
      </Chip>
      <div className="mt-2 text-sm text-white">{title}</div>
      {sourceEmail && (
        <div className="mt-3 flex items-start gap-2 rounded-xl bg-zinc-800 p-3">
          <Mail01Icon className="mt-0.5 size-3.5 shrink-0 text-zinc-500" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs text-zinc-400">
              {sourceEmail.sender}
            </div>
            <div className="truncate text-xs text-zinc-500">
              {sourceEmail.subject}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
