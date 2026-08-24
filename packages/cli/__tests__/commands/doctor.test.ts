import { execa, type ResultPromise } from "execa";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("execa", () => ({
  execa: vi.fn(),
}));

// version.ts uses createRequire on package.json, which breaks under vitest —
// stub the module (same approach as __tests__/lib/config.test.ts).
vi.mock("../../src/lib/version.js", () => ({
  CLI_VERSION: "0.0.1-test",
}));

import {
  areServicesRunning,
  checkApiHealth,
  checkComposeContainers,
  checkDiskHeadroom,
  checkDockerDaemon,
  checkSetupReadiness,
  checkWebReachable,
  classifyContainerState,
  describeUnhealthyServices,
  EXPECTED_SERVICES,
  evaluateSetupReadiness,
  MIN_DISK_HEADROOM_BYTES,
  parseDfAvailableKb,
  resolvePort,
} from "../../src/commands/doctor/checks.js";
import { hasBlockingFailure } from "../../src/commands/doctor/flow.js";
// Import after mocks are registered so the modules pick them up.
import type { CheckResult } from "../../src/commands/doctor/types.js";

const mockedExeca = vi.mocked(execa);

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Stub global fetch to resolve with the given options. */
function stubFetch(
  impl: (
    url: string,
    init?: RequestInit,
  ) => Promise<{ ok: boolean; status: number; json: () => Promise<unknown> }>,
): void {
  vi.stubGlobal("fetch", vi.fn(impl));
}

function okResponse(payload?: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  };
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------
describe("classifyContainerState", () => {
  it("maps running and restarting distinctly", () => {
    expect(classifyContainerState("running")).toBe("running");
    expect(classifyContainerState("restarting")).toBe("restarting");
  });

  it("collapses exited/created/dead/paused into stopped", () => {
    for (const raw of ["exited", "created", "dead", "paused"]) {
      expect(classifyContainerState(raw)).toBe("stopped");
    }
  });
});

describe("areServicesRunning / describeUnhealthyServices", () => {
  const expected = ["postgres", "gaia-web", "arq_worker"];

  it("is true only when every expected service is running", () => {
    const containers = [
      { service: "postgres", state: "running" },
      { service: "gaia-web", state: "running" },
      { service: "arq_worker", state: "running" },
      { service: "redis", state: "exited" },
    ];
    expect(areServicesRunning(containers, expected)).toBe(true);
  });

  it("counts restarting as not running", () => {
    const containers = [
      { service: "postgres", state: "running" },
      { service: "gaia-web", state: "running" },
      { service: "arq_worker", state: "restarting" },
    ];
    expect(areServicesRunning(containers, expected)).toBe(false);
  });

  it("reports missing and unhealthy services by name", () => {
    const containers = [
      { service: "postgres", state: "running" },
      { service: "gaia-web", state: "restarting" },
    ];
    expect(describeUnhealthyServices(containers, expected)).toBe(
      "gaia-web restarting, arq_worker missing",
    );
  });
});

describe("resolvePort", () => {
  it("uses the override when present", () => {
    expect(resolvePort({ 8000: 8123 }, 8000)).toBe(8123);
    expect(resolvePort({ 3000: 3100 }, 3000)).toBe(3100);
  });

  it("falls back to the default port", () => {
    expect(resolvePort({}, 8000)).toBe(8000);
    expect(resolvePort({ 5432: 5433 }, 8000)).toBe(8000);
  });
});

describe("evaluateSetupReadiness", () => {
  it("flags each unconfigured item with a setup-URL fix", () => {
    const items = evaluateSetupReadiness(
      {
        auth_mode: "workos",
        models_seeded: false,
        plans_seeded: false,
        has_admin_account: false,
        billing_enabled: false,
        providers: { openrouter: { configured: false } },
      },
      3000,
    );

    expect(items.map((i) => i.configured)).toEqual([
      false,
      false,
      false,
      false,
      false,
    ]);
    for (const item of items) {
      expect(item.fix).toBe(
        "Open http://localhost:3000/setup in your browser and complete first-run setup.",
      );
    }
  });

  it("passes when every item is configured", () => {
    const items = evaluateSetupReadiness(
      {
        auth_mode: "workos",
        models_seeded: true,
        plans_seeded: true,
        has_admin_account: true,
        billing_enabled: true,
        providers: {
          gemini: { configured: true },
          tavily: { configured: false },
        },
      },
      3000,
    );
    expect(items.every((i) => i.configured)).toBe(true);
  });

  it("treats any configured provider as the provider lane being ready", () => {
    const items = evaluateSetupReadiness(
      {
        providers: {
          ollama: { configured: true },
          openrouter: { configured: false },
        },
      },
      3000,
    );
    expect(
      items.find((i) => i.label === "LLM provider configured")?.configured,
    ).toBe(true);
  });

  it("drops the billing item for self-host instances (auth_mode local)", () => {
    // Self-host never enables billing — the backend pins billing_enabled to
    // ENV !== "selfhost". Requiring it here warned forever on every install.
    const items = evaluateSetupReadiness(
      {
        auth_mode: "local",
        models_seeded: true,
        plans_seeded: true,
        has_admin_account: true,
        billing_enabled: false,
        providers: { openrouter: { configured: true } },
      },
      3000,
    );

    expect(items.find((i) => i.label === "billing enabled")).toBeUndefined();
    expect(items.every((i) => i.configured)).toBe(true);
  });

  it("still reports other unconfigured items on a self-host instance", () => {
    const items = evaluateSetupReadiness(
      {
        auth_mode: "local",
        models_seeded: false,
        plans_seeded: true,
        has_admin_account: false,
        billing_enabled: false,
        providers: {},
      },
      3000,
    );

    // Billing is gone entirely; the remaining unconfigured items are intact.
    expect(items.find((i) => i.label === "billing enabled")).toBeUndefined();
    expect(items.filter((i) => !i.configured).map((i) => i.label)).toEqual([
      "models seeded",
      "LLM provider configured",
      "admin account created",
    ]);
  });
});

describe("parseDfAvailableKb", () => {
  it("parses the available column from df -k output", () => {
    const output = [
      "Filesystem   1024-blocks     Used Available Capacity iused ifree %iused  Mounted on",
      "/dev/disk3s1  4907268092 3810024 4903357068     1%       0     0    0% /",
    ].join("\n");
    expect(parseDfAvailableKb(output)).toBe(4903357068);
  });

  it("uses the last line when several filesystems are listed", () => {
    const output = [
      "map auto_home          0       0        0     0%       0     0    0% /System/Volumes/Data/home",
      "/dev/disk3s1  1000000 500000   500000    50%       0     0    0% /var/folders/x",
    ].join("\n");
    expect(parseDfAvailableKb(output)).toBe(500000);
  });

  it("returns null for malformed output", () => {
    expect(parseDfAvailableKb("")).toBeNull();
    expect(parseDfAvailableKb("only one column")).toBeNull();
    expect(parseDfAvailableKb("a b not-a-number d")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Individual checks
// ---------------------------------------------------------------------------
describe("checkDockerDaemon", () => {
  it("passes when docker info succeeds", async () => {
    mockedExeca.mockResolvedValueOnce({ stdout: "" } as Awaited<ResultPromise>);

    const result = await checkDockerDaemon();

    expect(result.state).toBe("ok");
    expect(mockedExeca).toHaveBeenCalledWith(
      "docker",
      expect.arrayContaining(["info"]),
    );
  });

  it("fails with an OrbStack/systemctl hint when unreachable", async () => {
    mockedExeca.mockRejectedValueOnce(
      new Error("Cannot connect to Docker daemon"),
    );

    const result = await checkDockerDaemon();

    expect(result.state).toBe("fail");
    expect(result.severity).toBe("blocker");
    expect(result.fix).toContain("OrbStack");
    expect(result.fix).toContain("systemctl start docker");
  });
});

describe("checkComposeContainers", () => {
  it("passes when all expected services are running", async () => {
    const stdout = [...EXPECTED_SERVICES["gaia-selfhost"]]
      .map((service) => `${service}|running`)
      .join("\n");
    mockedExeca.mockResolvedValueOnce({ stdout } as Awaited<ResultPromise>);

    const result = await checkComposeContainers({
      project: "gaia-selfhost",
      expected: EXPECTED_SERVICES["gaia-selfhost"],
    });

    expect(result.state).toBe("ok");
    expect(mockedExeca).toHaveBeenCalledWith(
      "docker",
      expect.arrayContaining([
        "label=com.docker.compose.project=gaia-selfhost",
      ]),
    );
  });

  it("fails naming missing/restarting/stopped services", async () => {
    const stdout = [
      "chromadb|running",
      "postgres|running",
      "redis|running",
      "mongo|running",
      "rabbitmq|running",
      "gaia-backend|restarting",
      // gaia-web missing entirely
      "arq_worker|exited",
    ].join("\n");
    mockedExeca.mockResolvedValueOnce({ stdout } as Awaited<ResultPromise>);

    const result = await checkComposeContainers({
      project: "gaia-selfhost",
      expected: EXPECTED_SERVICES["gaia-selfhost"],
    });

    expect(result.state).toBe("fail");
    expect(result.detail).toContain("gaia-web missing");
    expect(result.detail).toContain("gaia-backend restarting");
    expect(result.detail).toContain("arq_worker stopped");
    expect(result.fix).toContain("gaia start");
  });

  it("skips (not fails) when the daemon is down — already reported by check 1", async () => {
    mockedExeca.mockRejectedValueOnce(new Error("daemon down"));

    const result = await checkComposeContainers({
      project: "gaia-dev",
      expected: EXPECTED_SERVICES["gaia-dev"],
    });

    expect(result.state).toBe("skipped");
  });
});

describe("checkApiHealth", () => {
  it("passes on HTTP 200 from /health", async () => {
    stubFetch(async () => okResponse());

    const result = await checkApiHealth(8123);

    expect(result.state).toBe("ok");
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe(
      "http://localhost:8123/health",
    );
  });

  it("fails on error status codes", async () => {
    stubFetch(async () => ({ ok: false, status: 502, json: async () => ({}) }));

    const result = await checkApiHealth(8000);

    expect(result.state).toBe("fail");
    expect(result.detail).toContain("502");
  });

  it("fails on connection errors with a start hint", async () => {
    stubFetch(async () => {
      throw new Error("ECONNREFUSED");
    });

    const result = await checkApiHealth(8000);

    expect(result.state).toBe("fail");
    expect(result.fix).toContain("gaia start");
  });
});

describe("checkWebReachable", () => {
  it("issues a HEAD request to the web root", async () => {
    stubFetch(async () => okResponse());

    const result = await checkWebReachable(3000);

    expect(result.state).toBe("ok");
    const [url, init] = vi.mocked(fetch).mock.calls[0]!;
    expect(url).toBe("http://localhost:3000");
    expect(init?.method).toBe("HEAD");
  });

  it("fails on connection refused", async () => {
    stubFetch(async () => {
      throw new Error("ECONNREFUSED");
    });

    const result = await checkWebReachable(3000);

    expect(result.state).toBe("fail");
  });
});

describe("checkSetupReadiness", () => {
  it("emits one warning-level fail per unconfigured item", async () => {
    stubFetch(async () =>
      okResponse({
        auth_mode: "workos",
        models_seeded: true,
        plans_seeded: false,
        has_admin_account: true,
        billing_enabled: false,
        providers: {},
      }),
    );

    const results = await checkSetupReadiness({
      apiHealthy: true,
      apiPort: 8000,
      webPort: 3000,
    });

    expect(results).toHaveLength(3); // plans, provider lane, billing
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe(
      "http://localhost:8000/api/v1/setup/status",
    );
    for (const result of results) {
      expect(result.severity).toBe("warning");
      expect(result.state).toBe("fail");
      expect(result.fix).toContain("/setup in your browser");
    }
  });

  it("passes once every setup item is configured", async () => {
    stubFetch(async () =>
      okResponse({
        auth_mode: "workos",
        models_seeded: true,
        plans_seeded: true,
        has_admin_account: true,
        billing_enabled: true,
        providers: { openrouter: { configured: true } },
      }),
    );

    const results = await checkSetupReadiness({
      apiHealthy: true,
      apiPort: 8000,
      webPort: 3000,
    });

    expect(results).toHaveLength(1);
    expect(results[0]?.state).toBe("ok");
  });

  it("reports ok on a self-host instance with billing disabled", async () => {
    // The reported bug: every self-host install showed a permanent
    // "[warn] Billing enabled is not configured" because the backend sets
    // billing_enabled = (ENV !== "selfhost").
    stubFetch(async () =>
      okResponse({
        auth_mode: "local",
        models_seeded: true,
        plans_seeded: true,
        has_admin_account: true,
        billing_enabled: false,
        providers: { openrouter: { configured: true } },
      }),
    );

    const results = await checkSetupReadiness({
      apiHealthy: true,
      apiPort: 8000,
      webPort: 3000,
    });

    expect(results).toHaveLength(1);
    expect(results[0]?.state).toBe("ok");
    expect(results[0]?.label).toBe("Setup readiness");
  });

  it("skips when the API health check already failed", async () => {
    const results = await checkSetupReadiness({
      apiHealthy: false,
      apiPort: 8000,
      webPort: 3000,
    });

    expect(results).toHaveLength(1);
    expect(results[0]?.state).toBe("skipped");
  });
});

describe("checkDiskHeadroom", () => {
  it("resolves the Docker root dir via docker info and runs df on it", async () => {
    // docker info --format
    mockedExeca.mockResolvedValueOnce({
      stdout: "/var/lib/docker\n",
    } as Awaited<ResultPromise>);
    // df -k
    mockedExeca.mockResolvedValueOnce({
      stdout:
        "Filesystem 1024-blocks Used Available Capacity iused ifree %iused Mounted on\n" +
        "/dev/disk3s1 1000000000 1000 999999000 1% 0 0 0% /",
    } as Awaited<ResultPromise>);

    const result = await checkDiskHeadroom();

    expect(result.state).toBe("ok");
    expect(mockedExeca).toHaveBeenNthCalledWith(1, "docker", [
      "info",
      "--format",
      "{{.DockerRootDir}}",
    ]);
    expect(mockedExeca).toHaveBeenNthCalledWith(2, "df", [
      "-k",
      "/var/lib/docker",
    ]);
    expect(result.detail).toContain("953.7 GB free");
  });

  it("fails below the 2 GB threshold with a prune hint", async () => {
    mockedExeca.mockResolvedValueOnce({
      stdout: "/var/lib/docker",
    } as Awaited<ResultPromise>);
    // ~1 GB available in KB.
    const oneGbKb = Math.floor(MIN_DISK_HEADROOM_BYTES / 1024 / 2);
    mockedExeca.mockResolvedValueOnce({
      stdout: `Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 2000000 1000000 ${oneGbKb} 50% /`,
    } as Awaited<ResultPromise>);

    const result = await checkDiskHeadroom();

    expect(result.state).toBe("fail");
    expect(result.severity).toBe("blocker");
    expect(result.fix).toContain("docker system prune");
  });

  it("passes exactly at the 2 GB boundary", async () => {
    mockedExeca.mockResolvedValueOnce({
      stdout: "/var/lib/docker",
    } as Awaited<ResultPromise>);
    const twoGbKb = MIN_DISK_HEADROOM_BYTES / 1024;
    mockedExeca.mockResolvedValueOnce({
      stdout: `Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 4000000 2000000 ${twoGbKb} 50% /`,
    } as Awaited<ResultPromise>);

    const result = await checkDiskHeadroom();

    expect(result.state).toBe("ok");
  });

  it("skips when the daemon is unreachable", async () => {
    mockedExeca.mockRejectedValueOnce(new Error("daemon down"));

    const result = await checkDiskHeadroom();

    expect(result.state).toBe("skipped");
  });

  it("skips when df cannot be read instead of guessing", async () => {
    mockedExeca.mockResolvedValueOnce({
      stdout: "/var/lib/docker",
    } as Awaited<ResultPromise>);
    mockedExeca.mockRejectedValueOnce(new Error("df failed"));

    const result = await checkDiskHeadroom();

    expect(result.state).toBe("skipped");
  });
});

// ---------------------------------------------------------------------------
// Exit-code contract
// ---------------------------------------------------------------------------
describe("hasBlockingFailure", () => {
  function makeResult(overrides: Partial<CheckResult>): CheckResult {
    return {
      id: "check",
      label: "check",
      severity: "blocker",
      state: "ok",
      ...overrides,
    };
  }

  it.each<[string, Partial<CheckResult>, boolean]>([
    ["blocker fail → exit 1", { severity: "blocker", state: "fail" }, true],
    ["warning fail → exit 0", { severity: "warning", state: "fail" }, false],
    [
      "skipped blocker → exit 0",
      { severity: "blocker", state: "skipped" },
      false,
    ],
    ["all ok → exit 0", { severity: "blocker", state: "ok" }, false],
  ])("%s", (_name, overrides, expected) => {
    expect(hasBlockingFailure({ results: [makeResult(overrides)] })).toBe(
      expected,
    );
  });
});
