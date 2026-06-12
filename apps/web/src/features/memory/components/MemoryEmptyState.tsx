import type { ComponentType } from "react";

interface MemoryEmptyStateProps {
  readonly icon: ComponentType<{ className?: string }>;
  readonly title: string;
  readonly description?: string;
}

/**
 * Consistent empty-state treatment used across all memory tabs.
 * Icon + calm one-liner + optional sub-line, centred in a 48 height container.
 */
export function MemoryEmptyState({
  icon: Icon,
  title,
  description,
}: MemoryEmptyStateProps) {
  return (
    <div className="flex h-48 flex-col items-center justify-center gap-1 text-zinc-500">
      <Icon className="mb-2 size-8 opacity-40" />
      <p className="text-sm">{title}</p>
      {description && <p className="text-xs text-zinc-600">{description}</p>}
    </div>
  );
}
