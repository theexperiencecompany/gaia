import { execa } from "execa";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { findInstallRoot, detectSetupMode } = vi.hoisted(() => ({
  findInstallRoot: vi.fn(),
  detectSetupMode: vi.fn(),
}));
vi.mock("execa", () => ({ execa: vi.fn() }));
vi.mock("../../src/lib/service-starter.js", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  findInstallRoot,
  detectSetupMode,
}));

import { runStatusChecks } from "../../src/commands/status/flow.js";
import { CLIStore } from "../../src/ui/store.js";

const mockedExeca = vi.mocked(execa);

const SELFHOST_CONTAINERS = [
  "proxy|running|Up 2 minutes",
  "gaia-backend|running|Up 2 minutes (healthy)",
  "gaia-web|running|Up 2 minutes",
  "mongo|running|Up 2 minutes (healthy)",
].join("\n");

const READY = {
  status: "ready",
  dependencies: [{ name: "mongodb", ok: true, latency_ms: 3 }],
};

beforeEach(() => {
  vi.clearAllMocks();
  findInstallRoot.mockReturnValue("/no/such/install");
  detectSetupMode.mockResolvedValue("selfhost");
  mockedExeca.mockImplementation(((_cmd: string, args: string[]) =>
    Promise.resolve({
      stdout: args.includes("ps") ? SELFHOST_CONTAINERS : "",
    })) as unknown as typeof execa);
});

describe("gaia status on a self-host install", () => {
  it("reads container state from compose and readiness through the proxy only", async () => {
    const fetchMock = vi.fn(async (_url: string) => ({
      ok: true,
      status: 200,
      json: async () => READY,
    }));
    vi.stubGlobal("fetch", fetchMock);
    const store = new CLIStore();

    await runStatusChecks(store);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:3000/health/ready",
    ]);
    expect(store.currentState.data.services).toEqual([]);
    expect(store.currentState.data.docker.containers).toHaveLength(4);
    expect(store.currentState.status).toBe("4/4 containers running");
  });

  it("probes nothing when the install is not configured", async () => {
    detectSetupMode.mockResolvedValue(null);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const store = new CLIStore();

    await runStatusChecks(store);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(store.currentState.status).toBe(
      "Nothing to check: /no/such/install (not configured: no apps/api/.env)",
    );
  });
});
