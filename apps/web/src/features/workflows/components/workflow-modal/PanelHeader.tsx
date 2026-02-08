"use client";

import type { ReactNode } from "react";

interface PanelHeaderProps {
  /** Optional badge content (count, etc.) */
  badge?: ReactNode;
  /** Right-side action buttons */
  actions?: ReactNode;
}

/**
 * Shared header component for workflow modal panels (Steps, History, etc.)
 * Uses smaller, slightly darker, non-bold styling for consistency.
 */
export default function PanelHeader({ badge, actions }: PanelHeaderProps) {
  return (
    <div className="flex items-center justify-between pb-1">
      <div className="flex items-center gap-2">
        {badge && (
          <div className="text-sm text-zinc-400 font-medium">{badge}</div>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
