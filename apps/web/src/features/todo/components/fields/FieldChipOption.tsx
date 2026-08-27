import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface FieldChipOptionProps {
  onSelect: () => void;
  /** Visual variants (radius, text color, justification) on top of the base row. */
  className?: string;
  children: ReactNode;
}

/**
 * A clickable option row inside a field-chip popover (quick dates, priorities,
 * projects, clear actions). Rendered as a native button so keyboard users get
 * Enter/Space activation for free; callers layer their own visual classes.
 */
export default function FieldChipOption({
  onSelect,
  className,
  children,
}: FieldChipOptionProps) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
      className={cn(
        "flex w-full cursor-pointer items-center px-3 py-2 text-left transition-colors hover:bg-zinc-800",
        className,
      )}
    >
      {children}
    </button>
  );
}
