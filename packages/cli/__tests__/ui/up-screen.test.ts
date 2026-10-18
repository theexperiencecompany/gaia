import { stripVTControlCharacters } from "node:util";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

// version.ts uses createRequire on package.json, which breaks under vitest.
vi.mock("../../src/lib/version.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/lib/version.js")>()),
  CLI_VERSION: "0.0.1-test",
}));
// The header would read the install and the release cache, and go online.
vi.mock("../../src/ui/header/instance.js", () => ({
  availableUpdate: () => null,
  probeInstance: async () => null,
}));

import { UpScreen } from "../../src/commands/up/screen.js";
import type { UpOutcome } from "../../src/commands/up/summary.types.js";
import { finishStep, initSteps, startStep } from "../../src/lib/run-steps.js";
import { CLIStore } from "../../src/ui/store.js";
import { renderOn, tick } from "./fake-terminal.js";

const ESC = "\u001b";
/** ansi-escapes' clearTerminal: Ink writes it once a live frame fills the terminal. */
const CLEAR_SCROLLBACK = `${ESC}[3J`;

// The tallest real run: a fresh install that also saves an AI key.
const STEPS = [
  {
    id: "check",
    label: "Checking Git and Docker",
    doneLabel: "Git and Docker are ready",
  },
  { id: "download", label: "Downloading GAIA", doneLabel: "Downloaded GAIA" },
  { id: "configure", label: "Configuring GAIA", doneLabel: "Configured GAIA" },
  { id: "start", label: "Starting GAIA", doneLabel: "Started GAIA" },
  {
    id: "wait",
    label: "Waiting for GAIA to answer",
    doneLabel: "GAIA is answering",
  },
  {
    id: "provider",
    label: "Checking your OpenAI key",
    doneLabel: "Saved your OpenAI key",
  },
];

const READY: UpOutcome = {
  webUrl: "http://192.168.64.7:3000",
  reachableUrls: ["http://localhost:3000", "http://192.168.64.7:3000"],
  noStart: false,
  stillStarting: false,
  setupComplete: false,
  codeSandbox: false,
  savedProvider: "openai",
  joinedDockerGroup: true,
  elapsedMs: 82_000,
  startedServices: 9,
};

describe("UpScreen on an 80x24 terminal", () => {
  it("draws a whole run to the ready card without clearing the user's scrollback", async () => {
    const store = new CLIStore();
    const { stream, written, app } = renderOn(
      createElement(UpScreen, { store }),
      80,
      24,
    );

    initSteps(store, STEPS);
    for (const step of STEPS) {
      startStep(store, step.id);
      store.flush();
      await tick();
      finishStep(store, step.id);
      store.flush();
      await tick();
    }
    store.updateData("upOutcome", READY);
    store.updateData("finished", true);
    store.flush();
    await tick();
    // Ink clears on the redraw after a frame fills the terminal (a spinner tick, a resize).
    stream.emit("resize");
    await tick();
    app.unmount();

    expect(written()).toContain("GAIA is running");
    expect(written()).toContain("Saved your OpenAI key");
    expect(written()).not.toContain(CLEAR_SCROLLBACK);
  });

  it("starts no wrapped card line with a stray space", async () => {
    const store = new CLIStore();
    const { written, app } = renderOn(
      createElement(UpScreen, { store }),
      80,
      24,
    );
    store.updateData("upOutcome", READY);
    store.updateData("finished", true);
    store.flush();
    await tick();
    app.unmount();

    // The value column starts after the border, 2 columns of padding and the 16-column label.
    const continuations = stripVTControlCharacters(written())
      .split("\n")
      .filter((line) => /^│ {18}\S/.test(line) || /^│ {19}\S/.test(line));
    expect(continuations.length).toBeGreaterThan(0);
    for (const line of continuations) expect(line).toMatch(/^│ {18}\S/);
  });
});

describe("UpScreen when the start fails", () => {
  it("names the log once, inside the error", async () => {
    const store = new CLIStore();
    const { written, app } = renderOn(
      createElement(UpScreen, { store }),
      100,
      40,
      { debug: true },
    );
    initSteps(store, STEPS);
    startStep(store, "start");
    store.updateData("logPath", "/tmp/compose-up.log");
    store.setError(
      new Error(
        "The image gaia-missing:v1 was never built on this machine.\nFull log: /tmp/compose-up.log\nBuild the images here: gaia up --build.",
      ),
    );
    store.flush();
    await tick();
    app.unmount();

    const lastFrame =
      stripVTControlCharacters(written()).split("GAIA v0.0.1-test").at(-1) ??
      "";
    expect(lastFrame.match(/Full log:/g)).toHaveLength(1);
  });
});

describe("UpScreen after a docker-group relaunch", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("writes the header once: the first process already wrote it", async () => {
    const draw = async (): Promise<string> => {
      const store = new CLIStore();
      const { written, app } = renderOn(
        createElement(UpScreen, { store }),
        80,
        24,
      );
      initSteps(store, STEPS);
      store.flush();
      await tick();
      app.unmount();
      return stripVTControlCharacters(written());
    };

    expect(await draw()).toContain("GAIA v0.0.1-test");
    vi.stubEnv("GAIA_RESUMED_STEP", "Prerequisites");
    expect(await draw()).not.toContain("GAIA v0.0.1-test");
  });
});
