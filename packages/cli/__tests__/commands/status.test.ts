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

import {
  runStatusChecks,
  STATUS_FACTS_KEY,
} from "../../src/commands/status/flow.js";
import { buildStatusReport } from "../../src/commands/status/report.js";
import type { StatusFacts } from "../../src/commands/status/report.types.js";
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

/** The facts runStatusChecks gathered. */
function factsOf(store: CLIStore): StatusFacts {
  return store.currentState.data[STATUS_FACTS_KEY] as StatusFacts;
}

/** /health/ready answers READY; /setup/status says setup is still owed. */
function stubApi() {
  const fetchMock = vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () =>
      url.endsWith("/setup/status") ? { needs_setup: true } : READY,
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("gaia status on a self-host install", () => {
  it("reads containers from compose and health through the proxy only", async () => {
    const fetchMock = stubApi();
    const store = new CLIStore();

    await runStatusChecks(store);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:3000/health/ready",
      "http://localhost:3000/api/v1/setup/status",
    ]);
    const facts = factsOf(store);
    expect(facts.docker?.containers).toHaveLength(4);
    expect(facts.setupComplete).toBe(false);
    expect(store.currentState.data.checkedAt).toEqual(expect.any(String));
  });

  it("says running, in plain names, with the setup still owed", async () => {
    stubApi();
    const store = new CLIStore();

    await runStatusChecks(store);
    const report = buildStatusReport(factsOf(store));

    expect(report.headline.text).toBe("GAIA is running");
    expect(report.rows[0]?.items.map((i) => i.name)).toEqual([
      "web app",
      "server",
      "proxy",
    ]);
    expect(report.rows.find((r) => r.label === "Setup")?.note).toMatch(
      /^not finished · open http:\/\/.+:3000\/setup$/,
    );
    expect(report.unhealthy).toBe(false);
  });

  it("marks an enabled bot whose container was never created as down, and exits unhealthy", async () => {
    readConfig.mockReturnValue({ bots: ["telegram", "slack"] });
    mockedExeca.mockImplementation(((_cmd: string, args: string[]) =>
      Promise.resolve({
        stdout: args.includes("ps")
          ? `${SELFHOST_CONTAINERS}\nbot-telegram|running|Up 1 minute (healthy)`
          : "",
      })) as unknown as typeof execa);
    stubApi();
    const store = new CLIStore();

    await runStatusChecks(store);
    const report = buildStatusReport(factsOf(store));

    const bots = report.rows.find((r) => r.label === "Bots");
    expect(bots?.items).toEqual([
      { ok: true, name: "Telegram bot" },
      { ok: false, name: "Slack bot" },
    ]);
    expect(bots?.tone).toBe("fail");
    expect(report.unhealthy).toBe(true);
  });

  it("probes nothing when the install is not configured", async () => {
    detectSetupMode.mockResolvedValue(null);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const store = new CLIStore();

    await runStatusChecks(store);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(buildStatusReport(factsOf(store)).headline.text).toBe(
      "/no/such/install (not set up yet: no apps/api/.env) · run: gaia up",
    );
  });

  it("never calls a refused Docker socket 'not running'", () => {
    const report = buildStatusReport({
      install: "~/gaia (self-host)",
      installed: true,
      docker: {
        access: "no-permission",
        problem: {
          summary: "Docker is running, but your user can't use it yet",
          state: "is running, but your user can't use it yet",
          fix: "Log out and back in (or run 'newgrp docker'), then try again.",
        },
        containers: [],
      },
      services: [],
      setupComplete: null,
    });

    expect(report.headline.text).not.toMatch(/not running/i);
    expect(report.hint).toContain("newgrp docker");
  });

  // cli-audit 17: GAIA was up while this shell lacked the docker group.
  it("says GAIA is running when its API answers, though this terminal can't use Docker", () => {
    const report = buildStatusReport({
      install: "~/gaia (self-host)",
      installed: true,
      docker: {
        access: "no-permission",
        problem: {
          summary: "Docker is running, but your user can't use it yet",
          state: "is running, but your user can't use it yet",
          fix: "Log out and back in (or run 'newgrp docker'), then try again.",
        },
        containers: [],
      },
      readiness: {
        reachable: true,
        ready: true,
        dependencies: [{ name: "mongodb", ok: true, latency_ms: 2 }],
      },
      services: [],
      webUrl: "http://localhost:3000",
      setupComplete: true,
    });

    expect(report.headline).toEqual({
      kind: "ok",
      text: "GAIA is running",
      url: "http://localhost:3000",
    });
    expect(report.rows.at(-1)).toMatchObject({ label: "Docker", tone: "warn" });
  });
});
