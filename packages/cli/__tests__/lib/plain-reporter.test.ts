import { afterEach, describe, expect, it, vi } from "vitest";

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }));
vi.mock("node:child_process", () => ({ spawn }));

import {
  relaunchWithDockerGroup,
  resumedStep,
} from "../../src/lib/docker-group.js";
import { attachPlainReporter } from "../../src/lib/non-tty.js";
import {
  endActiveStep,
  finishStep,
  initSteps,
  startStep,
  updateStep,
} from "../../src/lib/run-steps.js";
import { CLIStore } from "../../src/ui/store.js";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("plain output across the docker-group relaunch", () => {
  it("hands the relaunched process the step it was in", () => {
    spawn.mockReturnValue({ on: vi.fn() });

    void relaunchWithDockerGroup("sg", { step: "Prerequisites", steps: {} });

    const env = spawn.mock.calls[0]?.[2]?.env as NodeJS.ProcessEnv;
    vi.stubEnv("GAIA_RESUMED_STEP", env.GAIA_RESUMED_STEP ?? "");
    expect(resumedStep()).toBe("Prerequisites");
  });

  it("keeps the environment through sudo, which resets it by default", () => {
    spawn.mockReturnValue({ on: vi.fn() });
    vi.stubEnv("DOCKER_HOST", "unix:///run/user/1000/docker.sock");

    void relaunchWithDockerGroup("sudo", { step: "Prerequisites", steps: {} });

    const [file, args] = spawn.mock.lastCall as [string, string[]];
    const preserved = args[0]?.replace("--preserve-env=", "").split(",");
    expect(file).toBe("sudo");
    expect(args.slice(1, 5)).toEqual(["-g", "docker", "--", process.execPath]);
    expect(preserved).toEqual(
      expect.arrayContaining([
        "DOCKER_HOST",
        "PATH",
        "GAIA_DOCKER_GROUP_RELAUNCHED",
        "GAIA_RESUMED_STEP",
      ]),
    );
  });
});

describe("plain output of a finished step's warnings", () => {
  it("prints each warning once, right after the step's line", () => {
    const lines: string[] = [];
    vi.spyOn(console, "info").mockImplementation((line: string) => {
      lines.push(line);
    });
    const store = new CLIStore();
    attachPlainReporter(store);
    initSteps(store, [
      { id: "preflight", label: "Checking", doneLabel: "GAIA can run here" },
    ]);
    startStep(store, "preflight");
    updateStep(store, "preflight", { warnings: ["Port 3000 was taken."] });
    finishStep(store, "preflight");
    store.flush();
    store.setStep("next");

    const printed = lines.join("\n").split("\n");
    const at = printed.findIndex((line) => line.includes("GAIA can run here"));
    expect(at).toBeGreaterThan(-1);
    expect(printed[at + 1]).toBe("    ! Port 3000 was taken.");
    expect(printed.filter((line) => line.includes("Port 3000"))).toHaveLength(
      1,
    );
  });
});

describe("plain output of a step that fails", () => {
  it("prints the failed step's row first, then its cause and fix indented under it", () => {
    const out: string[] = [];
    vi.spyOn(console, "info").mockImplementation((line: string) => {
      out.push(line);
    });
    vi.spyOn(process.stderr, "write").mockImplementation((chunk) => {
      out.push(String(chunk).replace(/\n$/, ""));
      return true;
    });
    const store = new CLIStore();
    attachPlainReporter(store);
    initSteps(store, [
      {
        id: "preflight",
        label: "Checking GAIA can run here",
        doneLabel: "GAIA can run here",
      },
    ]);
    startStep(store, "preflight", { startedAt: Date.now() - 1_000 });
    store.flush();
    store.setStatus("Checking ports…");
    store.flush();
    // The flow records the error, then ends the running step.
    store.setError(
      new Error(
        "Port 3001 is in use by another program.\nOr add --yes to let 'gaia up' pick free ports itself.",
      ),
    );
    store.flush();
    endActiveStep(store, "failed");
    store.flush();

    expect(out.join("\n").split("\n")).toEqual([
      "    Checking GAIA can run here…",
      "      Checking ports…",
      `  ✗ ${"Checking GAIA can run here".padEnd(36)}${"1s".padStart(8)}`,
      "    Port 3001 is in use by another program.",
      "    Or add --yes to let 'gaia up' pick free ports itself.",
    ]);
  });

  it("right-aligns a finished step's time in the column the screen uses", () => {
    const lines: string[] = [];
    vi.spyOn(console, "info").mockImplementation((line: string) => {
      lines.push(line);
    });
    const store = new CLIStore();
    attachPlainReporter(store);
    initSteps(store, [
      { id: "start", label: "Starting GAIA", doneLabel: "Started GAIA" },
    ]);
    startStep(store, "start", { startedAt: Date.now() - 73_000 });
    store.flush();
    finishStep(store, "start");
    store.flush();

    expect(lines.at(-1)).toBe(
      `  ✓ ${"Started GAIA".padEnd(36)}${"1m 13s".padStart(8)}`,
    );
  });
});
