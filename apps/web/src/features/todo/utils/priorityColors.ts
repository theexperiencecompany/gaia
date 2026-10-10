import { Priority } from "@shared/types";

/**
 * Canonical priority → text-color mapping (raw oklch values for inline styles).
 * Single source shared by TodoItem and the sidebar variants — do not re-declare
 * local copies.
 */
export const priorityTextColors: Record<Priority, string> = {
  [Priority.HIGH]: "oklch(63.7% 0.237 25.331)",
  [Priority.MEDIUM]: "oklch(79.5% 0.184 86.047)",
  [Priority.LOW]: "oklch(62.3% 0.214 259.815)",
  [Priority.NONE]: "oklch(55.2% 0.016 285.938)",
} as const;
