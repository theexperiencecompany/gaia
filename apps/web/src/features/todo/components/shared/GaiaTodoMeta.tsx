"use client";

import { AlertCircleIcon } from "@icons";
import type React from "react";
import { RetryTodoButton } from "@/features/todo/components/shared/RetryTodoButton";

interface GaiaTodoMetaProps {
  /** Why GAIA proposed/is executing this todo, e.g. "you asked about this last week". */
  serves?: string | null;
  /** Populated when execution failed — rendered loudly, not muted. */
  errorMessage?: string | null;
  /** When set alongside `errorMessage`, renders a Retry action for the failed run. */
  todoId?: string;
}

/**
 * Strips the bookkeeping lead-in the agent/system prepends to `serves`
 * ("Aryan confirmed: …", "user handoff: …") so the row shows only the reason.
 */
function cleanServes(serves: string): string {
  const trimmed = serves.trim();
  const colon = trimmed.indexOf(":");
  if (colon > 0 && colon < 40) {
    const lead = trimmed.slice(0, colon).toLowerCase();
    if (/confirmed|handoff|request|asked|goal/.test(lead)) {
      return trimmed.slice(colon + 1).trim();
    }
  }
  return trimmed;
}

/**
 * Shared "because: {serves}" and failure-reason lines for a GAIA-assigned
 * todo. Used in both the list row (`TodoItem`) and the detail view
 * (`TodoSidebar`) so the two surfaces never drift apart.
 */
export const GaiaTodoMeta: React.FC<GaiaTodoMetaProps> = ({
  serves,
  errorMessage,
  todoId,
}) => {
  if (!serves && !errorMessage) return null;

  return (
    <div className="mt-1 space-y-1">
      {serves && (
        <p className="truncate text-xs text-zinc-500">
          For: {cleanServes(serves)}
        </p>
      )}
      {errorMessage && (
        <p className="flex items-start gap-1 text-xs font-medium text-red-400">
          <AlertCircleIcon className="mt-0.5 size-3.5 shrink-0" />
          <span>{errorMessage}</span>
        </p>
      )}
      {errorMessage && todoId && (
        <div className="pt-1">
          <RetryTodoButton todoId={todoId} />
        </div>
      )}
    </div>
  );
};
