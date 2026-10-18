import { stripVTControlCharacters } from "node:util";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";
import type { RunStep } from "../../src/lib/run-steps.js";
import {
  endActiveStep,
  initSteps,
  resumableSteps,
  startStep,
  updateStep,
} from "../../src/lib/run-steps.js";
import {
  ActiveStep,
  splitFinished,
  stepCounter,
} from "../../src/ui/components/StepList.js";
import { CLIStore } from "../../src/ui/store.js";
import { renderOn } from "./fake-terminal.js";

const STEPS = [
  { id: "start", label: "Starting GAIA", doneLabel: "Started GAIA" },
  {
    id: "wait",
    label: "Almost ready",
    doneLabel: "GAIA is ready",
  },
];

function step(store: CLIStore, id: string): RunStep {
  const found = (store.currentState.data.steps as RunStep[]).find(
    (s) => s.id === id,
  );
  if (!found) throw new Error(`no step ${id}`);
  return found;
}

/** The screen lines an active step draws, as plain text. */
function draw(
  current: RunStep,
  options: { waiting?: boolean; counter?: string | null } = {},
): string[] {
  const { written, app } = renderOn(
    createElement(ActiveStep, {
      step: current,
      counter: options.counter ?? null,
      waiting: options.waiting ?? false,
      status: "",
    }),
    80,
    24,
    { debug: true },
  );
  app.unmount();
  return stripVTControlCharacters(written()).split("\n");
}

/** The first step after it has run for 19s, with or without a question on screen. */
function runningRow(waiting: boolean): string {
  const store = new CLIStore();
  initSteps(store, STEPS);
  startStep(store, "start", { startedAt: Date.now() - 19_000 });
  return (
    draw(step(store, "start"), { waiting }).find((line) =>
      line.includes("Starting GAIA"),
    ) ?? ""
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

describe("a running step's bar", () => {
  it("shows the amount done of the total and the time left beside the percentage", () => {
    const store = new CLIStore();
    initSteps(store, [
      { id: "download", label: "Downloading GAIA", doneLabel: "GAIA" },
    ]);
    startStep(store, "download");
    updateStep(store, "download", {
      amount: { done: 410e6, total: 660e6, unit: "bytes", estimated: false },
      etaMs: 70_000,
      detail: "5 of 9 images ready",
    });

    const lines = draw(step(store, "download"), { counter: "step 2 of 4" });

    expect(lines.find((l) => l.includes("Downloading GAIA"))).toMatch(
      /step 2 of 4/,
    );
    expect(
      lines.some((l) => l.includes("62%  410 / 660 MB · about 1 min left")),
    ).toBe(true);
    expect(lines.some((l) => l.includes("5 of 9 images ready"))).toBe(true);
  });

  it("draws no bar for a step that cannot say of how much", () => {
    const store = new CLIStore();
    initSteps(store, STEPS);
    startStep(store, "start", { percent: 40 });

    expect(draw(step(store, "start")).join("\n")).not.toMatch(/%/);
  });
});

describe("stepCounter", () => {
  const steps: RunStep[] = [
    { id: "docker", label: "", doneLabel: "", state: "done", minor: true },
    { id: "download", label: "", doneLabel: "", state: "skipped" },
    { id: "start", label: "", doneLabel: "", state: "active" },
    { id: "wait", label: "", doneLabel: "", state: "pending" },
  ];

  it("counts only the real steps that still have something to do", () => {
    expect(stepCounter(steps, steps[2] as RunStep)).toBe("step 1 of 2");
  });

  it("gives housekeeping no number", () => {
    expect(stepCounter(steps, steps[0] as RunStep)).toBeNull();
  });
});

describe("splitFinished", () => {
  it("keeps only the leading finished steps out of the live frame", () => {
    const steps = [
      { id: "a", label: "A", doneLabel: "A", state: "done" as const },
      { id: "b", label: "B", doneLabel: "B", state: "active" as const },
      { id: "c", label: "C", doneLabel: "C", state: "done" as const },
    ];

    const { finished, live } = splitFinished(steps);

    expect(finished.map((s) => s.id)).toEqual(["a"]);
    expect(live.map((s) => s.id)).toEqual(["b", "c"]);
  });

  it("lists a slow housekeeping step but folds a quick one and a skipped one away", () => {
    const steps: RunStep[] = [
      {
        id: "files",
        label: "",
        doneLabel: "Got GAIA's setup files",
        state: "done",
        minor: true,
        startedAt: 0,
        endedAt: 400,
      },
      {
        id: "docker",
        label: "",
        doneLabel: "Docker installed",
        state: "done",
        minor: true,
        startedAt: 0,
        endedAt: 130_000,
      },
      { id: "download", label: "", doneLabel: "", state: "skipped" },
      { id: "start", label: "", doneLabel: "", state: "active" },
    ];

    const { finished, live } = splitFinished(steps);

    expect(finished.map((s) => s.id)).toEqual(["docker"]);
    expect(live.map((s) => s.id)).toEqual(["start"]);
  });
});

describe("initSteps after a docker-group relaunch", () => {
  it("keeps the start time and the done label the first process gave each step", () => {
    const store = new CLIStore();
    const startedAt = Date.now() - 200_000;
    vi.stubEnv(
      "GAIA_RESUMED_STEPS",
      JSON.stringify({
        start: { startedAt, doneLabel: "Docker installed", minor: false },
      }),
    );
    initSteps(store, [
      {
        id: "start",
        label: "Checking Docker",
        doneLabel: "Docker is ready",
        minor: true,
      },
    ]);
    startStep(store, "start");
    vi.unstubAllEnvs();

    expect(resumableSteps(store)).toEqual({
      start: { startedAt, doneLabel: "Docker installed", minor: false },
    });
  });
});

describe("a step cancelled with Ctrl-C", () => {
  it("ends on the cancelled mark, not a frozen spinner", () => {
    const store = new CLIStore();
    initSteps(store, STEPS);
    startStep(store, "start");
    endActiveStep(store, "cancelled");
    const row =
      draw(step(store, "start")).find((line) =>
        line.includes("Starting GAIA"),
      ) ?? "";

    expect(row.trimStart().startsWith("■")).toBe(true);
  });
});
