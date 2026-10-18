import { stripVTControlCharacters } from "node:util";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";
import type { RunStep } from "../../src/lib/run-steps.js";
import {
  advanceSubstep,
  endActiveStep,
  initSteps,
  resumableSteps,
  startStep,
  updateStep,
} from "../../src/lib/run-steps.js";
import {
  ActiveStep,
  FinishedStep,
  splitFinished,
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
function draw(current: RunStep, options: { waiting?: boolean } = {}): string[] {
  const { written, app } = renderOn(
    createElement(ActiveStep, {
      step: current,
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

// Real run: "Named GAIA gaia.local on your network11s" outgrew the label column.
describe("a label longer than the column", () => {
  const LONG = "A step label far longer than the label column";

  it("keeps a gap before the time on a finished step", () => {
    const { written, app } = renderOn(
      createElement(FinishedStep, {
        step: {
          id: "long",
          label: LONG,
          doneLabel: LONG,
          state: "done",
          startedAt: 0,
          endedAt: 11_000,
        },
      }),
      100,
      24,
      { debug: true },
    );
    app.unmount();

    expect(stripVTControlCharacters(written())).toMatch(
      new RegExp(`${LONG} {2,}11s`),
    );
  });

  it("keeps a gap before the time on the running step", () => {
    const store = new CLIStore();
    initSteps(store, [{ id: "long", label: LONG, doneLabel: LONG }]);
    startStep(store, "long", { startedAt: Date.now() - 11_000 });

    expect(draw(step(store, "long"), { waiting: false }).join("\n")).toMatch(
      new RegExp(`${LONG} {2,}11s`),
    );
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

    const lines = draw(step(store, "download"));

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

describe("a running step's lines", () => {
  const STAGES = [
    { id: "download", label: "Downloading packages" },
    { id: "install", label: "Installing packages" },
    { id: "start", label: "Starting Docker" },
  ];

  function dockerLines(): string[] {
    const store = new CLIStore();
    initSteps(store, [
      { id: "docker", label: "Installing Docker", doneLabel: "Docker" },
    ]);
    startStep(store, "docker", { startedAt: Date.now() - 62_000 });
    advanceSubstep(store, "docker", STAGES, "install", "containerd.io");
    return draw(step(store, "docker"));
  }

  it("marks the stages before the running one done and leaves the later ones unmarked", () => {
    const lines = dockerLines();
    const line = (label: string): string =>
      lines.find((l) => l.includes(label)) ?? "";

    expect(line("Downloading packages").trimStart().startsWith("✓")).toBe(true);
    expect(
      line("Starting Docker").trimStart().startsWith("Starting Docker"),
    ).toBe(true);
    expect(line("Installing packages")).toContain("containerd.io");
  });

  it("ends each line's note where the step's time ends", () => {
    const lines = dockerLines();
    const end = (text: string): number => {
      const line = lines.find((l) => l.includes(text)) ?? "";
      return line.indexOf(text) + text.length;
    };

    expect(end("containerd.io · 0s")).toBe(end("1m 02s"));
  });

  it("gives the running line its own clock, kept while its note changes", () => {
    vi.useFakeTimers({ now: 1_000_000 });
    try {
      const store = new CLIStore();
      initSteps(store, [
        { id: "docker", label: "Installing Docker", doneLabel: "Docker" },
      ]);
      startStep(store, "docker", { startedAt: Date.now() - 62_000 });
      advanceSubstep(store, "docker", STAGES, "start", "containerd starting");
      vi.setSystemTime(1_009_000);
      advanceSubstep(store, "docker", STAGES, "start", "dockerd starting");
      const lines = draw(step(store, "docker"));

      expect(lines.find((l) => l.includes("Starting Docker"))).toContain(
        "dockerd starting · 9s",
      );
      expect(lines.find((l) => l.includes("Installing packages"))).not.toMatch(
        /\ds/,
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("replaces the step's plain detail line", () => {
    const store = new CLIStore();
    initSteps(store, STEPS);
    startStep(store, "start", { detail: "a plain line" });
    advanceSubstep(store, "start", STAGES, "download");

    expect(draw(step(store, "start")).join("\n")).not.toContain("a plain line");
  });
});

describe("finished steps", () => {
  it("right-align their times in one column", () => {
    const row = (label: string, ms: number): string => {
      const { written, app } = renderOn(
        createElement(FinishedStep, {
          step: {
            id: label,
            label,
            doneLabel: label,
            state: "done",
            startedAt: 0,
            endedAt: ms,
          },
        }),
        100,
        24,
        { debug: true },
      );
      app.unmount();
      return (
        stripVTControlCharacters(written())
          .split("\n")
          .find((l) => l.includes(label)) ?? ""
      ).trimEnd();
    };

    expect(row("Docker installed", 172_000).length).toBe(
      row("Started GAIA", 9_000).length,
    );
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
        start: {
          startedAt,
          label: "Installing Docker",
          doneLabel: "Docker installed",
          minor: false,
        },
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
      start: {
        startedAt,
        label: "Installing Docker",
        doneLabel: "Docker installed",
        minor: false,
      },
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
