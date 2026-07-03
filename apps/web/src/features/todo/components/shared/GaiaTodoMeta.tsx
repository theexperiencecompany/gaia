"use client";

import { AlertCircleIcon } from "@icons";
import type React from "react";

interface GaiaTodoMetaProps {
  /** Why GAIA proposed/is executing this todo, e.g. "you asked about this last week". */
  serves?: string | null;
  /** Populated when execution failed — rendered loudly, not muted. */
  errorMessage?: string | null;
}

/**
 * Shared "because: {serves}" and failure-reason lines for a GAIA-assigned
 * todo. Used in both the list row (`TodoItem`) and the detail view
 * (`TodoSidebar`) so the two surfaces never drift apart.
 */
export const GaiaTodoMeta: React.FC<GaiaTodoMetaProps> = ({
  serves,
  errorMessage,
}) => {
  if (!serves && !errorMessage) return null;

  return (
    <div className="mt-1 space-y-1">
      {serves && (
        <p className="truncate text-xs text-zinc-500">because: {serves}</p>
      )}
      {errorMessage && (
        <p className="flex items-start gap-1 text-xs font-medium text-red-400">
          <AlertCircleIcon className="mt-0.5 size-3.5 shrink-0" />
          <span>{errorMessage}</span>
        </p>
      )}
    </div>
  );
};
