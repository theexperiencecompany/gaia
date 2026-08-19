import { Priority } from "@/types/features/todoTypes";

export const priorityTextColors = {
  [Priority.HIGH]: "oklch(63.7% 0.237 25.331)",
  [Priority.MEDIUM]: "oklch(79.5% 0.184 86.047)",
  [Priority.LOW]: "oklch(62.3% 0.214 259.815)",
  [Priority.NONE]: "oklch(55.2% 0.016 285.938)",
} as const;
