import { afterEach, describe, expect, it, vi } from "vitest";

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }));
vi.mock("node:child_process", () => ({ spawn }));

import {
  relaunchWithDockerGroup,
  resumedStep,
} from "../../src/lib/docker-group.js";

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
