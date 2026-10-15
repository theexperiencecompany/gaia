import { Console } from "node:console";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../src/lib/non-tty.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/non-tty.js")>()),
  isInteractive: () => true,
}));
vi.mock("../../src/lib/version.js", () => ({ CLI_VERSION: "0.0.1-test" }));

import { runCommandUI } from "../../src/lib/command-runner.js";

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
        store.updateData("upWebUrl", "http://localhost:3000");
        store.updateData("upReachableUrls", ["http://localhost:3000"]);
        store.updateData("upApiUrl", "http://localhost:3000/api/v1");
        store.updateData("finished", true);
        store.setStep("Finished");
      },
    });
    await exited;

    expect(written).toContain("GAIA is ready!");
  });
});
