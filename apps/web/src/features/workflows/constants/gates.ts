/**
 * Copy and limits for a gate's "Runs only when" row, shared by the workflow
 * editor and the tracked-todo sidebar so both read the same way.
 */

export const RUNS_ONLY_WHEN_LABEL = "Runs only when";

/** The API's TRIGGER_GATE_CONDITION_MAX_CHARS; the server refuses a longer condition. */
export const GATE_CONDITION_MAX_CHARS = 300;

export const GATE_CONDITION_PLACEHOLDER =
  "Leave empty to run on every event, or describe the ones worth a run, like emails from customers about billing";

export const GATE_SWITCH_LABEL = "Use this condition";

/** A rule whose kind is still in shadow: GAIA decides each event but skips none. */
export const GATE_SHADOW_NOTE =
  "GAIA is still learning this rule. Every event runs for now.";

export const GATE_OFF_NOTE = "Off, so every event runs.";
