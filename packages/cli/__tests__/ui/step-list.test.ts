import { stripVTControlCharacters } from "node:util";
import { createElement } from "react";
import { describe, expect, it } from "vitest";
import type { RunStep } from "../../src/lib/run-steps.js";
import {
  endActiveStep,
  initSteps,
  startStep,
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

describe("a step cancelled with Ctrl-C", () => {
  it("ends on the cancelled mark, not a frozen spinner", () => {
    expect(cancelledRow().trimStart().startsWith("■")).toBe(true);
  });
});
