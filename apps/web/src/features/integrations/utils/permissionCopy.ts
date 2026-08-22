import type { HilMode } from "@shared/chat";

/** Search only earns its place once the list is too long to scan. */
export const SEARCH_THRESHOLD = 12;

/**
 * The only grouping the real tool data supports is `destructive`, and it is
 * coarser than it looks — Gmail classifies "Create Email Draft" and "Move To
 * Trash" as non-destructive — so the second group promises nothing about what
 * its tools do, only how GAIA treats them by default.
 */
export const TOOL_SECTIONS: {
  key: string;
  title: string;
  destructive: boolean;
}[] = [
  { key: "risky", title: "Risky actions", destructive: true },
  { key: "rest", title: "Everything else", destructive: false },
];

/**
 * The mode says what happens to the tools picked below — never how many tools
 * are covered, which is the list's job (`policy.py`: the gated set is identical
 * in `auto` and `always_ask`). Describing it as scope is what let the old copy
 * promise "every change" while the list showed none were picked.
 */
export const MODE_OPTIONS: {
  mode: HilMode;
  label: string;
  description: string;
}[] = [
  {
    mode: "auto",
    label: "Auto",
    description: "Only when an action goes beyond what you asked for.",
  },
  {
    mode: "always_ask",
    label: "Every time",
    description: "Before every action you turned on below.",
  },
  {
    mode: "always_allow",
    label: "Never",
    description: "GAIA runs everything without stopping.",
  },
];

/** In this mode per-tool preferences are stored but have no effect at all. */
export const isModeInert = (mode: HilMode): boolean => mode === "always_allow";
