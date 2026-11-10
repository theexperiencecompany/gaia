import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../src/lib/non-tty.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/non-tty.js")>()),
  isInteractive: () => false,
}));
vi.mock("../../src/ui/header/header-lines.js", () => ({
  printHeader: async () => undefined,
}));

import { setEnding } from "../../src/lib/command-ending.js";
import { runCommandUI } from "../../src/lib/command-runner.js";
import { finishStep, initSteps, startStep } from "../../src/lib/run-steps.js";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("runCommandUI without a terminal", () => {
  // Real run: `gaia stop | cat` printed "Stopping GAIA…" and the ending, never "✓ Stopped GAIA".
  it("prints a step that finished right before the flow returned, above the ending", async () => {
    const lines: string[] = [];
    vi.spyOn(console, "info").mockImplementation((line: string) => {
      lines.push(line);
    });
    const exited = new Promise<void>((resolve) => {
      vi.spyOn(process, "exit").mockImplementation((() => {
        resolve();
      }) as typeof process.exit);
    });

    await runCommandUI({
      command: "run",
      whenNonInteractive: "plain",
      runFlow: async (store) => {
        initSteps(store, [
          { id: "stop", label: "Stopping GAIA", doneLabel: "Stopped GAIA" },
        ]);
        startStep(store, "stop");
        finishStep(store, "stop");
        setEnding(store, { lead: "Start it again:", target: "gaia start" });
      },
    });
    await exited;

    const done = lines.findIndex((line) => line.includes("✓ Stopped GAIA"));
    expect(done).toBeGreaterThan(-1);
    expect(done).toBeLessThan(
      lines.findIndex((line) => line.includes("Start it again:")),
    );
  });
});
