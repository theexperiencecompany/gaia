import { stripVTControlCharacters } from "node:util";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";
import type { RunStep } from "../../src/lib/run-steps.js";
import {
  endActiveStep,
  initSteps,
  startStep,
  stepStartTimes,
} from "../../src/lib/run-steps.js";
import { StepList } from "../../src/ui/components/StepList.js";
import { CLIStore } from "../../src/ui/store.js";
import { renderOn } from "./fake-terminal.js";

const STEPS = [
  { id: "start", label: "Starting GAIA", doneLabel: "Started GAIA" },
  {
    id: "wait",
    label: "Waiting for GAIA to answer",
    doneLabel: "GAIA is answering",
  },
];

/** The running step after Ctrl-C, as the step list draws it. */
function cancelledRow(): string {
  const store = new CLIStore();
  initSteps(store, STEPS);
  startStep(store, "start");
  endActiveStep(store, "cancelled");
  const steps = store.currentState.data.steps as RunStep[];
  const { written, app } = renderOn(
    createElement(StepList, { steps, waiting: false, status: "" }),
    80,
    24,
    { debug: true },
  );
  app.unmount();
  return (
    stripVTControlCharacters(written())
      .split("\n")
      .find((line) => line.includes("Starting GAIA")) ?? ""
  );
}

/** The first step's row while it has run for 19s, with or without a question on screen. */
function runningRow(waiting: boolean): string {
  const store = new CLIStore();
  initSteps(store, STEPS);
  startStep(store, "start", { startedAt: Date.now() - 19_000 });
  const steps = store.currentState.data.steps as RunStep[];
  const { written, app } = renderOn(
    createElement(StepList, { steps, waiting, status: "" }),
    80,
    24,
    { debug: true },
  );
  app.unmount();
  return (
    stripVTControlCharacters(written())
      .split("\n")
      .find((line) => line.includes("Starting GAIA")) ?? ""
  );
}

describe("a running step's timer", () => {
  it("ticks while the step works", () => {
    expect(runningRow(false)).toMatch(/Starting GAIA\s+19s/);
  });

  it("is hidden while the run waits on an answer", () => {
    expect(runningRow(true)).not.toMatch(/\d+s/);
  });
});

describe("initSteps after a docker-group relaunch", () => {
  it("keeps the start time the first process gave each step", () => {
    const store = new CLIStore();
    const startedAt = Date.now() - 200_000;
    vi.stubEnv(
      "GAIA_RESUMED_STEP_STARTS",
      JSON.stringify({ start: startedAt }),
    );
    initSteps(store, STEPS);
    startStep(store, "start");
    vi.unstubAllEnvs();

    expect(stepStartTimes(store)).toEqual({ start: startedAt });
  });
});

describe("a step cancelled with Ctrl-C", () => {
  it("ends on the cancelled mark, not a frozen spinner", () => {
    expect(cancelledRow().trimStart().startsWith("■")).toBe(true);
  });
});
