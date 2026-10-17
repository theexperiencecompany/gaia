import { describe, expect, it, vi } from "vitest";

vi.mock("execa", () => ({
  execa: vi.fn(() => Promise.reject(new Error("ENOENT"))),
}));
vi.mock("node:os", async (importOriginal) => ({
  ...(await importOriginal<typeof import("node:os")>()),
  platform: () => "darwin",
}));
vi.mock("../../src/lib/service-starter.js", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("../../src/lib/service-starter.js")
  >()),
  isGaiaCheckout: () => false,
}));
vi.mock("../../src/lib/version.js", () => ({ CLI_VERSION: "0.0.1-test" }));

import { runUpFlow } from "../../src/commands/up/flow.js";
import type { RunStep } from "../../src/lib/run-steps.js";
import { createStore } from "../../src/ui/store.js";

describe("gaia up without git on a fresh machine", () => {
  it("stops at git and never leaves Docker's check spinning", async () => {
    const store = createStore();

    await runUpFlow(store);

    expect(store.currentState.error?.message).toMatch(/GAIA needs Git/);
    expect(store.currentState.data.checks).toEqual({ git: "error" });
  });

  it("names a --build start for what it does, which is not only on a first run", async () => {
    const store = createStore();

    await runUpFlow(store, { build: true });

    const start = (store.currentState.data.steps as RunStep[]).find(
      (step) => step.id === "start",
    );
    expect(start?.label).toBe("Building GAIA");
    expect(start?.doneLabel).toBe("Built and started GAIA");
  });
});
