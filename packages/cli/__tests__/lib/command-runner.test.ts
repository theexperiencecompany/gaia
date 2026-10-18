import { Console } from "node:console";
import { stripVTControlCharacters } from "node:util";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../src/lib/non-tty.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/non-tty.js")>()),
  isInteractive: () => true,
}));
vi.mock("../../src/lib/version.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/version.js")>()),
  CLI_VERSION: "0.0.1-test",
}));

import { runCommandUI } from "../../src/lib/command-runner.js";
import { initSteps, startStep } from "../../src/lib/run-steps.js";

/** Everything Ink wrote to stdout during the test. */
let written = "";

beforeEach(() => {
  written = "";
  // Ink patches the console (vitest's has no Console class) and reads keys
  // through a raw-mode stdin, as it does in a real terminal.
  vi.stubGlobal("console", Object.assign(Object.create(console), { Console }));
  Object.defineProperty(process.stdin, "isTTY", {
    value: true,
    configurable: true,
  });
  process.stdin.setRawMode = vi.fn(() => process.stdin);
  vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
    written += String(chunk);
    return true;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(process.stdin, "isTTY");
});

describe("runCommandUI under a terminal", () => {
  it("renders the flow's last state before it exits", async () => {
    const exited = new Promise<void>((resolve) => {
      vi.spyOn(process, "exit").mockImplementation((() => {
        resolve();
      }) as typeof process.exit);
    });

    await runCommandUI({
      command: "up",
      whenNonInteractive: "plain",
      runFlow: async (store) => {
        store.updateData("upOutcome", {
          webUrl: "http://localhost:3000",
          reachableUrls: ["http://localhost:3000"],
          noStart: false,
          stillStarting: false,
          setupComplete: false,
          codeSandbox: false,
          joinedDockerGroup: false,
          elapsedMs: 5000,
          startedServices: 9,
        });
        store.updateData("finished", true);
        store.setStep("Finished");
      },
    });
    await exited;

    expect(written).toContain("GAIA is running · ready in 5s");
    // The shell prompt starts on its own line, not glued to the last frame.
    expect(written.endsWith("\n")).toBe(true);
  });

  // Real run: Ctrl-C mid-clone left the frame with its spinner frozen on the step.
  it("draws the running step as cancelled before it exits on Ctrl-C", async () => {
    const exited = new Promise<void>((resolve) => {
      vi.spyOn(process, "exit").mockImplementation((() => {
        resolve();
      }) as typeof process.exit);
    });

    void runCommandUI({
      command: "up",
      whenNonInteractive: "plain",
      runFlow: async (store) => {
        initSteps(store, [
          {
            id: "download",
            label: "Downloading GAIA",
            doneLabel: "Downloaded GAIA",
          },
        ]);
        startStep(store, "download");
        await new Promise((resolve) => setTimeout(resolve, 100));
        process.stdin.push("\u0003");
        await exited;
      },
    });
    await exited;

    expect(stripVTControlCharacters(written)).toContain("■ Downloading GAIA");
  });

  // Real run: `gaia stop` exited with its result line never drawn, because
  // the last change was still inside the store's throttle window.
  it("draws a last change that arrived inside the throttle window", async () => {
    const exited = new Promise<void>((resolve) => {
      vi.spyOn(process, "exit").mockImplementation((() => {
        resolve();
      }) as typeof process.exit);
    });

    await runCommandUI({
      command: "stop",
      whenNonInteractive: "plain",
      runFlow: async (store) => {
        store.setStep("Stopped");
        store.setStatus("GAIA stopped. Start it again with 'gaia start'.");
        store.updateData("stopped", true);
      },
    });
    await exited;

    expect(written).toContain(
      "GAIA stopped. Start it again with 'gaia start'.",
    );
  });
});
