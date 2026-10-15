import { afterEach, describe, expect, it, vi } from "vitest";

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }));
vi.mock("node:child_process", () => ({ spawn }));

import {
  relaunchWithDockerGroup,
  resumedStep,
} from "../../src/lib/docker-group.js";
import { attachPlainReporter } from "../../src/lib/non-tty.js";
import { CLIStore } from "../../src/ui/store.js";

/** Everything the plain reporter printed while the steps ran. */
function printedFor(steps: string[], resumed?: string): string[] {
  const lines: string[] = [];
  vi.spyOn(console, "info").mockImplementation((line: string) => {
    lines.push(line);
  });
  const store = new CLIStore();
  attachPlainReporter(store, resumed);
  for (const step of steps) store.setStep(step);
  return lines;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("plain output across the docker-group relaunch", () => {
  it("continues under the step the first process was in, without repeating its header", () => {
    expect(
      printedFor(["Prerequisites", "Repository Setup"], "Prerequisites"),
    ).toEqual(["\n[Repository Setup]"]);
  });

  it("prints every step header on a first run", () => {
    expect(printedFor(["Prerequisites", "Repository Setup"])).toEqual([
      "\n[Prerequisites]",
      "\n[Repository Setup]",
    ]);
  });

  it("hands the relaunched process the step it was in", () => {
    spawn.mockReturnValue({ on: vi.fn() });

    void relaunchWithDockerGroup("Prerequisites", "sg");

    const env = spawn.mock.calls[0]?.[2]?.env as NodeJS.ProcessEnv;
    vi.stubEnv("GAIA_RESUMED_STEP", env.GAIA_RESUMED_STEP ?? "");
    expect(resumedStep()).toBe("Prerequisites");
  });

  it("keeps the environment through sudo, which resets it by default", () => {
    spawn.mockReturnValue({ on: vi.fn() });
    vi.stubEnv("DOCKER_HOST", "unix:///run/user/1000/docker.sock");

    void relaunchWithDockerGroup("Prerequisites", "sudo");

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
