/**
 * A command's visible step list: each step has a present-tense label while it
 * runs, a past-tense one once done, its own timer, and an optional detail line
 * and percentage. Flows drive it through the store; the screen and the plain
 * (non-TTY) reporter both read it.
 * @module lib/run-steps
 */

import type { CLIStore } from "../ui/store.js";
import { type ResumedStep, resumedSteps } from "./docker-group.js";
import type { ProgressAmount } from "./progress.js";
import type { RunSubstep } from "./run-steps.types.js";

export type RunStepState =
  | "pending"
  | "active"
  | "waiting"
  | "done"
  | "failed"
  | "cancelled"
  /** Turned out to have nothing to do (the images were already here). */
  | "skipped";

export interface RunStep {
  id: string;
  /** Present participle while it runs ("Downloading GAIA"). */
  label: string;
  /** Past tense once done ("Downloaded GAIA"). */
  doneLabel: string;
  state: RunStepState;
  startedAt?: number;
  endedAt?: number;
  /** One plain line under a running step, e.g. "5 of 9 images ready". */
  detail?: string;
  /** The bar's position, 0-100; without it the bar follows amount. */
  percent?: number;
  /** How much is done of how much, shown beside the bar. */
  amount?: ProgressAmount;
  /** Milliseconds left, when the step can tell. */
  etaMs?: number | null;
  /** When amount last grew: a step whose bytes stop moving says so. */
  amountMovedAt?: number;
  /**
   * Housekeeping between the real steps (reading the setup files, saving
   * settings): not counted in "Step n of N", and not listed once done when it
   * was quick.
   */
  minor?: boolean;
  /** A dim note under a running step, e.g. how long it usually takes. */
  hint?: string;
  /** The lines under a running step, in order; dropped once it is done. */
  substeps?: RunSubstep[];
  /** What a step found that needs attention but did not stop the run; kept once done. */
  warnings?: string[];
}

export const STEPS_KEY = "steps";

function readSteps(store: CLIStore): RunStep[] {
  return (store.currentState.data[STEPS_KEY] ?? []) as RunStep[];
}

/**
 * Lay out the steps a run will show, all pending. After a docker-group
 * relaunch, a step the first process began keeps its start time and what it
 * was becoming (Installing Docker stays "Docker installed").
 */
export function initSteps(
  store: CLIStore,
  steps: readonly Pick<RunStep, "id" | "label" | "doneLabel" | "minor">[],
): void {
  const resumed = resumedSteps();
  store.updateData(
    STEPS_KEY,
    steps.map((step) => ({
      ...step,
      ...resumed[step.id],
      state: "pending" as const,
    })),
  );
}

/** Every step that has begun, as a docker-group relaunch carries it over. */
export function resumableSteps(store: CLIStore): Record<string, ResumedStep> {
  return Object.fromEntries(
    readSteps(store).flatMap((step) =>
      step.startedAt === undefined
        ? []
        : [
            [
              step.id,
              {
                startedAt: step.startedAt,
                label: step.label,
                doneLabel: step.doneLabel,
                minor: step.minor,
                substeps: step.substeps,
              },
            ],
          ],
    ),
  );
}

export function findStep(store: CLIStore, id: string): RunStep | undefined {
  return readSteps(store).find((step) => step.id === id);
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
      step.id === id
        ? { ...step, ...patch, ...amountMoved(step, patch.amount) }
        : step,
    ),
  );
}

/** A fresh amountMovedAt when the patch's amount is further along than the step's. */
function amountMoved(
  step: RunStep,
  amount: ProgressAmount | undefined,
): Pick<RunStep, "amountMovedAt"> {
  if (!amount) return {};
  const moved = !step.amount || amount.done > step.amount.done;
  return moved ? { amountMovedAt: Date.now() } : {};
}

export function startStep(
  store: CLIStore,
  id: string,
  patch: Partial<Omit<RunStep, "id">> = {},
): void {
  const now = Date.now();
  const step = readSteps(store).find((s) => s.id === id);
  // The status line belonged to the step before; a new step starts without it.
  store.setStatus("");
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
    amount: undefined,
    etaMs: undefined,
    hint: undefined,
    substeps: undefined,
    ...(doneLabel ? { doneLabel } : {}),
  });
}

/**
 * Make `at` the running line under a step: the stages before it done, the
 * ones after still to come, `note` beside it. Its clock starts when it first runs.
 */
export function advanceSubstep(
  store: CLIStore,
  id: string,
  stages: readonly Pick<RunSubstep, "id" | "label">[],
  at: string,
  note?: string,
): void {
  const index = stages.findIndex((stage) => stage.id === at);
  const running = readSteps(store)
    .find((s) => s.id === id)
    ?.substeps?.find((substep) => substep.state === "active");
  const startedAt =
    running?.id === at ? (running.startedAt ?? Date.now()) : Date.now();
  updateStep(store, id, {
    substeps: stages.map((stage, i) => ({
      ...stage,
      state: i < index ? "done" : i === index ? "active" : "pending",
      ...(i === index ? { startedAt } : {}),
      ...(i === index && note ? { note } : {}),
    })),
  });
}

/** Mark a step that had nothing to do; the screen leaves it out. */
export function skipStep(store: CLIStore, id: string): void {
  updateStep(store, id, { state: "skipped", endedAt: Date.now() });
}

/** End the running step as failed (the error is shown separately) or cancelled (Ctrl-C). */
export function endActiveStep(
  store: CLIStore,
  state: "failed" | "cancelled",
): void {
  const active = readSteps(store).find(
    (s) => s.state === "active" || s.state === "waiting",
  );
  if (active) updateStep(store, active.id, { state, endedAt: Date.now() });
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
