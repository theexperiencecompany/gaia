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
  isGaiaInstall: () => false,
}));
vi.mock("../../src/lib/version.js", () => ({ CLI_VERSION: "0.0.1-test" }));

import { runUpFlow } from "../../src/commands/up/flow.js";
import type { RunStep } from "../../src/lib/run-steps.js";
import { createStore } from "../../src/ui/store.js";

describe("gaia up on a fresh machine", () => {
  it("never asks for git, and never leaves Docker's check spinning", async () => {
    const store = createStore();

    await runUpFlow(store);

    expect(store.currentState.error?.message).not.toMatch(/Git/);
    expect(store.currentState.data.checks).toEqual({ docker: "error" });
    const docker = (store.currentState.data.steps as RunStep[]).find(
      (step) => step.id === "docker",
    );
    expect(docker?.state).toBe("failed");
  });

  it("folds waiting for GAIA into the start, and names gaia.local in a label that fits", async () => {
    const store = createStore();

    await runUpFlow(store);

    const steps = store.currentState.data.steps as RunStep[];
    expect(steps.map((step) => step.id)).not.toContain("wait");
    expect(steps.find((step) => step.id === "local-name")?.doneLabel).toBe(
      "gaia.local set up",
    );
  });

  it("names a --build start for what it does, which is not only on a first run", async () => {
    const store = createStore();

    await runUpFlow(store, { build: true });

    const download = (store.currentState.data.steps as RunStep[]).find(
      (step) => step.id === "download",
    );
    expect(download?.label).toBe("Building GAIA");
    expect(download?.doneLabel).toBe("Built GAIA");
  });
});
