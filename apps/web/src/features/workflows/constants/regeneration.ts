/**
 * Step-regeneration reasons — the single source of truth shared by the steps
 * panel dropdown (label/description/icon) and the modal orchestrator
 * (instruction sent to the regenerate API). Keeping these together stops the
 * dropdown copy and the API instruction from silently drifting apart.
 */

import {
  Minimize01Icon,
  PlusSignIcon,
  ShuffleIcon,
  Wrench01Icon,
} from "@icons";
import type { FC } from "react";

export interface RegenerationReason {
  /** Stable key used as the dropdown item id. */
  key: string;
  /** Dropdown label. */
  label: string;
  /** Dropdown secondary description. */
  description: string;
  /** Instruction string sent to the regenerate-steps API. */
  instruction: string;
  icon: FC<{ className?: string }>;
}

export const REGENERATION_REASONS: readonly RegenerationReason[] = [
  {
    key: "too_complex",
    label: "Too complex",
    description: "Simplify with fewer steps",
    instruction: "Simplify workflow",
    icon: Minimize01Icon,
  },
  {
    key: "missing_functionality",
    label: "Missing functionality",
    description: "Add specific features",
    instruction: "Add missing functionality",
    icon: PlusSignIcon,
  },
  {
    key: "wrong_tools",
    label: "Wrong tools",
    description: "Use different integrations",
    instruction: "Use different tools",
    icon: Wrench01Icon,
  },
  {
    key: "alternative_approach",
    label: "Alternative approach",
    description: "Try a completely different strategy",
    instruction: "Generate alternative approach",
    icon: ShuffleIcon,
  },
] as const;
