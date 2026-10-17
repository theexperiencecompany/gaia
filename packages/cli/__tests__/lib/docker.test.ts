import { execa, type ResultPromise } from "execa";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("execa", () => ({
  execa: vi.fn(),
}));

import {
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
