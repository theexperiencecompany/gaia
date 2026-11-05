/**
 * Copy and limits for a gate's "Runs only when" panel, shared by the workflow
 * editor and the tracked-todo sidebar so both read the same way.
 */

export const RUNS_ONLY_WHEN_LABEL = "Runs only when";

/** The API's TRIGGER_GATE_CONDITION_MAX_CHARS; the server refuses a longer condition. */
export const GATE_CONDITION_MAX_CHARS = 300;

export const GATE_CONDITION_PLACEHOLDER =
  "Describe the events worth a run, like emails from customers about billing";

export const GATE_SWITCH_LABEL = "Use this rule";

/** Who wrote the rule, as the panel's subtitle says it. */
export const GATE_AUTHOR_LINES = {
  gaia: "GAIA wrote this rule from your task",
  user: "You wrote this rule",
  system: "Built into this task",
} as const;

export type GateAuthorLine = keyof typeof GATE_AUTHOR_LINES;

/** What a working rule does, in one sentence. */
export const GATE_EXPLAINER =
  "GAIA checks every new event and skips the rest, so this only runs when it matters.";

/** A rule whose kind is still in shadow: GAIA decides each event but skips none. */
export const GATE_SHADOW_NOTE =
  "GAIA is still learning this rule, so every event runs for now.";

export const GATE_OFF_NOTE = "Off, so every event runs.";

export const GATE_NO_SKIPS_NOTE = "Nothing skipped yet.";

export const GATE_RECENT_SKIPS_LABEL = "Recently skipped";

export const GATE_EMPTY_TITLE = "Runs on every event";

export const GATE_EMPTY_NOTE =
  "Add a rule and GAIA will skip the events that don't need this.";
