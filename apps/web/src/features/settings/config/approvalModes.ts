import type { HilMode } from "@shared/chat";

/** The one wording for the three approval modes, shared by Settings and every integration's permissions. */
export const APPROVAL_MODES: {
  mode: HilMode;
  label: string;
  description: string;
}[] = [
  {
    mode: "always_ask",
    label: "Ask every time",
    description: "GAIA checks with you before every risky action.",
  },
  {
    mode: "auto",
    label: "Ask when unsure",
    description:
      "GAIA runs what you clearly asked for and checks with you about anything else.",
  },
  {
    mode: "always_allow",
    label: "Never ask",
    description:
      "GAIA runs every action without checking, except a few account changes that always need your OK.",
  },
];

export const ALWAYS_ASKS_LABEL = "Always asks";

/** The registry's always_gate tools and an account disconnect ask in every mode (services/hil/policy.py). */
export const ALWAYS_ASKS_NOTE =
  "Changing your settings or saved instructions, pairing a device, adding a tool server, and disconnecting an account always need your OK, whichever mode you pick.";

export const APPROVALS_SECTION_DESCRIPTION =
  "Choose when GAIA checks with you before it sends, deletes, or posts something for you.";

export const approvalModeLabel = (mode: HilMode): string =>
  APPROVAL_MODES.find((option) => option.mode === mode)?.label ?? mode;
