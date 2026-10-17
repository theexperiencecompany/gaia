import { execa } from "execa";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { findInstallRoot, detectSetupMode, readConfig } = vi.hoisted(() => ({
  findInstallRoot: vi.fn(),
  detectSetupMode: vi.fn(),
  readConfig: vi.fn(),
}));
vi.mock("execa", () => ({ execa: vi.fn() }));
vi.mock("../../src/lib/config.js", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  readConfig,
}));
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
  readConfig.mockReturnValue(null);
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
    expect(store.currentState.status).toBe("4 of 4 services running");
    expect(store.currentState.data.checkedAt).toEqual(expect.any(String));
    expect(store.currentState.data.refreshable).toBe(true);
  });

  it("lists an enabled bot whose container was never created as not running", async () => {
    readConfig.mockReturnValue({ bots: ["telegram", "slack"] });
    mockedExeca.mockImplementation(((_cmd: string, args: string[]) =>
      Promise.resolve({
        stdout: args.includes("ps")
          ? `${SELFHOST_CONTAINERS}\nbot-telegram|running|Up 1 minute (healthy)`
          : "",
      })) as unknown as typeof execa);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, json: async () => READY })),
    );
    const store = new CLIStore();

    await runStatusChecks(store);

    expect(store.currentState.data.docker.containers.slice(-2)).toEqual([
      { name: "bot-telegram", status: "running", health: "healthy" },
      { name: "bot-slack", status: "not_found" },
    ]);
    expect(store.currentState.status).toBe("5 of 6 services running");
  });

  it("probes nothing when the install is not configured", async () => {
    detectSetupMode.mockResolvedValue(null);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const store = new CLIStore();

    await runStatusChecks(store);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(store.currentState.status).toBe(
      "Run 'gaia up' to finish setting it up.",
    );
    expect(store.currentState.data.install).toBe(
      "/no/such/install (not set up yet: no apps/api/.env)",
    );
    expect(store.currentState.data.checkedAt).toEqual(expect.any(String));
  });
});
