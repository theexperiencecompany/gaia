import { execa, type ResultPromise } from "execa";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("execa", () => ({
  execa: vi.fn(),
}));

import {
  assertDockerSupportsGaia,
  assertEngineSupportsCodeSandbox,
  dockerVolumeExists,
  getContainerStatuses,
  getProjectPublishedPorts,
} from "../../src/lib/docker.js";

const mockedExeca = vi.mocked(execa);

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// getContainerStatuses
// ---------------------------------------------------------------------------
describe("getContainerStatuses", () => {
  it("lists the project's containers by compose service, with health", async () => {
    mockedExeca.mockResolvedValueOnce({
      stdout: [
        "gaia-backend|running|Up 3 minutes (healthy)",
        "rabbitmq|exited|Exited (0) 2 minutes ago",
        "arq_worker|running|Up 3 minutes (health: starting)",
        "proxy|running|Up 1 minute",
      ].join("\n"),
    } as Awaited<ResultPromise>);

    const result = await getContainerStatuses("gaia-selfhost");

    expect(mockedExeca).toHaveBeenCalledWith("docker", [
      "ps",
      "-a",
      "--filter",
      "label=com.docker.compose.project=gaia-selfhost",
      "--format",
      '{{.Label "com.docker.compose.service"}}|{{.State}}|{{.Status}}',
    ]);
    expect(result).toEqual([
      { name: "gaia-backend", status: "running", health: "healthy" },
      { name: "rabbitmq", status: "stopped", health: undefined },
      { name: "arq_worker", status: "running", health: "health: starting" },
      { name: "proxy", status: "running", health: undefined },
    ]);
  });
});

// ---------------------------------------------------------------------------
// getProjectPublishedPorts
// ---------------------------------------------------------------------------
describe("getProjectPublishedPorts", () => {
  it("collects host ports from every published mapping", async () => {
    mockedExeca.mockResolvedValueOnce({
      stdout: [
        "0.0.0.0:3000->80/tcp, [::]:3000->80/tcp, 0.0.0.0:3443->443/tcp",
        "8000/tcp",
      ].join("\n"),
    } as Awaited<ResultPromise>);

    const ports = await getProjectPublishedPorts("gaia-selfhost");

    expect([...ports].sort()).toEqual([3000, 3443]);
  });
});

describe("assertEngineSupportsCodeSandbox", () => {
  const engine = (stdout: string) =>
    mockedExeca.mockResolvedValueOnce({ stdout } as Awaited<ResultPromise>);

  it.each(["26.0.0", "29.1.3"])("accepts Docker Engine %s", async (v) => {
    engine(v);
    await expect(assertEngineSupportsCodeSandbox()).resolves.toBeUndefined();
  });

  it.each(["25.0.5", "20.10.24", ""])(
    "refuses Docker Engine '%s'",
    async (v) => {
      engine(v);
      await expect(assertEngineSupportsCodeSandbox()).rejects.toThrow(
        "Docker Engine 26 or newer",
      );
    },
  );
});

describe("assertDockerSupportsGaia", () => {
  /** Answer `docker compose version --short`, then `docker version`'s server version. */
  function versions(compose: string, engine: string): void {
    mockedExeca
      .mockResolvedValueOnce({ stdout: compose } as Awaited<ResultPromise>)
      .mockResolvedValueOnce({ stdout: engine } as Awaited<ResultPromise>);
  }

  it.each([
    ["2.29.1", "25.0.0"],
    ["v2.40.3", "28.5.1"],
    ["5.5.0", "29.8.2"],
  ])("accepts Compose %s on Engine %s", async (compose, engine) => {
    versions(compose, engine);
    await expect(assertDockerSupportsGaia()).resolves.toBeUndefined();
  });

  // Ubuntu 24.04's docker-compose-v2 package ships 2.24-2.27, which rejects --progress json.
  it("refuses an older Compose with the version it needs and how to upgrade", async () => {
    mockedExeca.mockResolvedValueOnce({
      stdout: "2.24.6",
    } as Awaited<ResultPromise>);
    const error = assertDockerSupportsGaia();
    await expect(error).rejects.toThrow(/Compose 2\.29\.1 or newer.*2\.24\.6/s);
    await expect(error).rejects.toThrow(/docker-compose-plugin/);
  });

  it("says the Compose plugin is missing, not a raw docker error", async () => {
    mockedExeca.mockRejectedValueOnce(
      Object.assign(new Error("Command failed"), {
        stderr: "docker: 'compose' is not a docker command.",
      }),
    );
    await expect(assertDockerSupportsGaia()).rejects.toThrow(
      /Docker Compose isn't installed/,
    );
  });

  // Compose refuses healthcheck.start_interval below Engine 25 (API 1.44).
  it("refuses an Engine older than 25", async () => {
    versions("2.30.0", "24.0.7");
    await expect(assertDockerSupportsGaia()).rejects.toThrow(
      /Docker Engine 25 or newer.*24\.0\.7/s,
    );
  });
});

describe("dockerVolumeExists", () => {
  it("matches the exact volume name only", async () => {
    mockedExeca.mockResolvedValueOnce({
      stdout: "gaia-sandbox-workspace",
    } as Awaited<ResultPromise>);
    expect(await dockerVolumeExists("gaia-sandbox-workspace")).toBe(true);
    expect(mockedExeca).toHaveBeenCalledWith("docker", [
      "volume",
      "ls",
      "--quiet",
      "--filter",
      "name=^gaia-sandbox-workspace$",
    ]);

    mockedExeca.mockResolvedValueOnce({ stdout: "" } as Awaited<ResultPromise>);
    expect(await dockerVolumeExists("gaia-sandbox-workspace")).toBe(false);
  });
});
