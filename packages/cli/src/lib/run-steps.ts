/**
 * A command's visible step list: each step has a present-tense label while it
 * runs, a past-tense one once done, its own timer, and an optional detail line
 * and percentage. Flows drive it through the store; the screen and the plain
 * (non-TTY) reporter both read it.
 * @module lib/run-steps
 */

import type { CLIStore } from "../ui/store.js";

export type RunStepState = "pending" | "active" | "waiting" | "done" | "failed";

export interface RunStep {
  id: string;
  /** Present participle while it runs ("Downloading GAIA"). */
  label: string;
  /** Past tense once done ("Downloaded GAIA"). */
  doneLabel: string;
  state: RunStepState;
  startedAt?: number;
  endedAt?: number;
  /** One line under a running step, e.g. "412 MB of 1.3 GB". */
  detail?: string;
  percent?: number;
  /** A dim note under a running step, e.g. how long it usually takes. */
  hint?: string;
}

export const STEPS_KEY = "steps";

function readSteps(store: CLIStore): RunStep[] {
  return (store.currentState.data[STEPS_KEY] ?? []) as RunStep[];
}

/** Lay out the steps a run will show, all pending. */
export function initSteps(
  store: CLIStore,
  steps: readonly Pick<RunStep, "id" | "label" | "doneLabel">[],
): void {
  store.updateData(
    STEPS_KEY,
    steps.map((step) => ({ ...step, state: "pending" as const })),
  );
}

/** Change one step; patches merge into it. */
export function updateStep(
  store: CLIStore,
  id: string,
  patch: Partial<Omit<RunStep, "id">>,
): void {
  store.updateData(
    STEPS_KEY,
    readSteps(store).map((step) =>
      step.id === id ? { ...step, ...patch } : step,
    ),
  );
}

export function startStep(
  store: CLIStore,
  id: string,
  patch: Partial<Omit<RunStep, "id">> = {},
): void {
  const now = Date.now();
  const step = readSteps(store).find((s) => s.id === id);
  updateStep(store, id, {
    state: "active",
    startedAt: step?.startedAt ?? now,
    ...patch,
  });
}

/** Mark a step done: it keeps its final duration and drops its live detail. */
export function finishStep(
  store: CLIStore,
  id: string,
  doneLabel?: string,
): void {
  const step = readSteps(store).find((s) => s.id === id);
  updateStep(store, id, {
    state: "done",
    endedAt: Date.now(),
    startedAt: step?.startedAt ?? Date.now(),
    detail: undefined,
    percent: undefined,
    hint: undefined,
    ...(doneLabel ? { doneLabel } : {}),
  });
}

/** Mark the running step failed (the error itself is shown separately). */
export function failActiveStep(store: CLIStore): void {
  const active = readSteps(store).find(
    (s) => s.state === "active" || s.state === "waiting",
  );
  if (active)
    updateStep(store, active.id, { state: "failed", endedAt: Date.now() });
}

/** 12s, 6m 12s, 1h 04m. */
export function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60)
    return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}
