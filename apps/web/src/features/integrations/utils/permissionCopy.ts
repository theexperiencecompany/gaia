import type { HilMode } from "@shared/chat";
import { approvalModeLabel } from "@/features/settings/config/approvalModes";

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
  {
    key: "risky",
    title: "GAIA asks about these by default",
    destructive: true,
  },
  {
    key: "rest",
    title: "GAIA runs these without asking by default",
    destructive: false,
  },
];

/** The never-ask banner: per-tool choices are kept but ignored until the mode changes. */
export const INERT_MODE_NOTICE = `You picked ${approvalModeLabel("always_allow")}, so GAIA won't stop for any of these.`;

export const INERT_MODE_SWITCH_TO: HilMode = "auto";

export const INERT_MODE_SWITCH_LABEL = `Switch to ${approvalModeLabel(INERT_MODE_SWITCH_TO)}`;

/** In this mode per-tool preferences are stored but have no effect at all. */
export const isModeInert = (mode: HilMode): boolean => mode === "always_allow";
