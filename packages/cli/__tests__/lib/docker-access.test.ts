import * as os from "node:os";
import { execa } from "execa";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("execa", () => ({ execa: vi.fn() }));
vi.mock("node:os", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:os")>();
  return { ...actual, platform: vi.fn(() => "linux") };
});

import {
  describeDockerProblem,
  getDockerAccess,
} from "../../src/lib/docker-access.js";
import { getDockerStatus } from "../../src/lib/healthcheck.js";

const mockedExeca = vi.mocked(execa);

const SOCKET_REFUSED = Object.assign(new Error("Command failed: docker info"), {
  stderr:
    "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock",
});

/** `docker info` fails like this; `id -nG` lists these groups. */
function dockerFails(error: Error, groups = "aryan sudo"): void {
  mockedExeca.mockImplementation(((cmd: string) =>
    cmd === "id"
      ? Promise.resolve({ stdout: groups })
      : Promise.reject(error)) as unknown as typeof execa);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(os.platform).mockReturnValue("linux");
});

describe("getDockerAccess", () => {
  it("is ready when docker info answers", async () => {
    mockedExeca.mockResolvedValueOnce({ stdout: "ok" } as never);
    expect(await getDockerAccess()).toBe("ready");
  });

  it("tells a missing docker binary apart from a stopped daemon", async () => {
    dockerFails(
      Object.assign(new Error("spawn docker ENOENT"), { code: "ENOENT" }),
    );
    expect(await getDockerAccess()).toBe("not-installed");

    dockerFails(new Error("Cannot connect to the Docker daemon"));
    expect(await getDockerAccess()).toBe("not-running");
  });

  it("reports a refused socket as its own state, not as Docker being down", async () => {
    dockerFails(SOCKET_REFUSED);
    expect(await getDockerAccess()).toBe("no-permission");
  });
});

describe("describeDockerProblem", () => {
  it("tells a user who just joined the group to log out and in, or run newgrp", async () => {
    dockerFails(SOCKET_REFUSED, "aryan sudo docker");
    const problem = await describeDockerProblem("no-permission");

    expect(problem.summary).toBe(
      "Docker is running, but your user can't use it yet",
    );
    expect(problem.fix).toContain("Log out and back in");
    expect(problem.fix).toContain("newgrp docker");
  });

  it("tells a user outside the group how to join it", async () => {
    dockerFails(SOCKET_REFUSED, "aryan sudo");
    const problem = await describeDockerProblem("no-permission");

    expect(problem.fix).toContain("sudo usermod -aG docker $USER");
  });

  it("says Docker isn't installed when it isn't", async () => {
    const problem = await describeDockerProblem("not-installed");
    expect(problem.summary).toBe("Docker isn't installed");
  });
});

describe("gaia status with Docker's socket refusing the user", () => {
  it("reports the permission problem and its fix, not 'not running'", async () => {
    dockerFails(SOCKET_REFUSED, "aryan docker");

    const status = await getDockerStatus("selfhost");

    expect(status.access).toBe("no-permission");
    expect(status.problem?.summary).not.toMatch(/not running/i);
    expect(status.problem?.fix).toContain("newgrp docker");
    expect(status.containers).toEqual([]);
  });
});
