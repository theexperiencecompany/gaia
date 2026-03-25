import { execa, type ResultPromise } from "execa";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("execa", () => ({
  execa: vi.fn(),
}));

import { getContainerStatuses, isDockerRunning } from "../../src/lib/docker.js";

const mockedExeca = vi.mocked(execa);

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// getContainerStatuses
// ---------------------------------------------------------------------------
describe("getContainerStatuses", () => {
  const CONTAINER_NAMES = [
    "gaia-backend",
    "gaia-web",
    "chromadb",
    "postgres",
    "redis",
    "mongo",
    "rabbitmq",
    "arq_worker",
  ];

  it("parses batch docker inspect output correctly", async () => {
    const inspectOutput = [
      "/gaia-backend|running|none",
      "/gaia-web|running|healthy",
      "/chromadb|running|none",
      "/postgres|running|healthy",
      "/redis|running|none",
      "/mongo|running|none",
      "/rabbitmq|exited|none",
      "/arq_worker|running|none",
    ].join("\n");

    mockedExeca.mockResolvedValueOnce({
      stdout: inspectOutput,
    } as Awaited<ResultPromise>);

    const result = await getContainerStatuses();

    expect(result).toHaveLength(8);
    expect(mockedExeca).toHaveBeenCalledWith("docker", [
      "inspect",
      "--format",
      "{{.Name}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
      ...CONTAINER_NAMES,
    ]);
  });

  it("maps running/stopped/not_found statuses", async () => {
    const inspectOutput = [
      "/gaia-backend|running|none",
      "/gaia-web|exited|none",
      "/chromadb|running|none",
      "/postgres|running|none",
      "/redis|running|none",
      "/mongo|running|none",
      "/rabbitmq|running|none",
      // arq_worker missing from output
    ].join("\n");

    mockedExeca.mockResolvedValueOnce({
      stdout: inspectOutput,
    } as Awaited<ResultPromise>);

    const result = await getContainerStatuses();

    const backend = result.find((c) => c.name === "gaia-backend");
    const web = result.find((c) => c.name === "gaia-web");
    const worker = result.find((c) => c.name === "arq_worker");

    expect(backend?.status).toBe("running");
    expect(web?.status).toBe("stopped");
    expect(worker?.status).toBe("not_found");
  });

  it("includes health status when present", async () => {
    const inspectOutput = [
      "/gaia-backend|running|none",
      "/gaia-web|running|healthy",
      "/chromadb|running|unhealthy",
      "/postgres|running|none",
      "/redis|running|none",
      "/mongo|running|none",
      "/rabbitmq|running|none",
      "/arq_worker|running|none",
    ].join("\n");

    mockedExeca.mockResolvedValueOnce({
      stdout: inspectOutput,
    } as Awaited<ResultPromise>);

    const result = await getContainerStatuses();

    const web = result.find((c) => c.name === "gaia-web");
    const chromadb = result.find((c) => c.name === "chromadb");
    const backend = result.find((c) => c.name === "gaia-backend");

    expect(web?.health).toBe("healthy");
    expect(chromadb?.health).toBe("unhealthy");
    expect(backend?.health).toBeUndefined();
  });

  it("falls back to individual inspects on batch failure", async () => {
    // Batch call fails
    mockedExeca.mockRejectedValueOnce(new Error("batch inspect failed"));

    // Individual calls — make all succeed except one
    for (const name of CONTAINER_NAMES) {
      if (name === "arq_worker") {
        mockedExeca.mockRejectedValueOnce(new Error("not found"));
      } else {
        mockedExeca.mockResolvedValueOnce({
          stdout: "running|none",
        } as Awaited<ResultPromise>);
      }
    }

    const result = await getContainerStatuses();

    expect(result).toHaveLength(8);

    // The first call is the batch that fails, then 8 individual calls
    expect(mockedExeca).toHaveBeenCalledTimes(9);

    const worker = result.find((c) => c.name === "arq_worker");
    expect(worker?.status).toBe("not_found");

    const backend = result.find((c) => c.name === "gaia-backend");
    expect(backend?.status).toBe("running");
  });

  it("returns not_found for containers that don't exist (fallback path)", async () => {
    // Batch call fails
    mockedExeca.mockRejectedValueOnce(new Error("batch inspect failed"));

    // All individual calls fail
    for (const _ of CONTAINER_NAMES) {
      mockedExeca.mockRejectedValueOnce(new Error("not found"));
    }

    const result = await getContainerStatuses();

    for (const container of result) {
      expect(container.status).toBe("not_found");
    }
  });
});

// ---------------------------------------------------------------------------
// isDockerRunning
// ---------------------------------------------------------------------------
describe("isDockerRunning", () => {
  it("returns true when docker info succeeds", async () => {
    mockedExeca.mockResolvedValueOnce({
      stdout: "some docker info",
    } as Awaited<ResultPromise>);

    const result = await isDockerRunning();

    expect(result).toBe(true);
    expect(mockedExeca).toHaveBeenCalledWith("docker", ["info"]);
  });

  it("returns false when docker info fails", async () => {
    mockedExeca.mockRejectedValueOnce(
      new Error("Cannot connect to Docker daemon"),
    );

    const result = await isDockerRunning();

    expect(result).toBe(false);
  });
});
