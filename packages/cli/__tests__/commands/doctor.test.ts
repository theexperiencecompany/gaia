import { stripVTControlCharacters } from "node:util";
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
  checkBots,
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
  unconfiguredInstallCheck,
} from "../../src/commands/doctor/checks.js";
import { hasBlockingFailure } from "../../src/commands/doctor/flow.js";
import { printDoctorReport } from "../../src/commands/doctor/handler.js";
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

/** The catalog's chat-capable providers, as GET /setup/catalog serves them. */
const LLM_KEYS = ["openrouter", "gemini", "openai", "ollama", "custom"];

/** Serve a /setup/status payload plus the catalog its LLM readiness is read against. */
function stubSetupEndpoints(status: unknown): void {
  stubFetch(async (url) =>
    okResponse(
      url.endsWith("/api/v1/setup/catalog")
        ? {
            providers: {},
            custom_presets: {},
            features: {},
            llm_provider_keys: LLM_KEYS,
          }
        : status,
    ),
  );
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
        needs_setup: true,
        wizard_dismissed: false,
        features: {},
        plans_seeded: false,
        bots: {
          telegram_username: null,
          discord_client_id: null,
          slack_workspace_url: null,
        },
        has_admin_account: false,
        registration_policy: "invite_only",
        deployment: {
          kind: "production",
          bills: true,
          local_code_sandbox: false,
          blob_store: "local",
          gaia_support: false,
          instance_toolkits: false,
          private_network_endpoints: false,
        },
        providers: {
          openrouter: {
            configured: false,
            source: "unset",
            env_shadowed: false,
          },
        },
      },
      LLM_KEYS,
      3000,
    );

    expect(items.map((i) => i.configured)).toEqual([false, false, false]);
    for (const item of items) {
      expect(item.fix).toBe(
        "Open http://localhost:3000/setup in your browser to finish setting GAIA up.",
      );
    }
  });

  it("passes when every item is configured", () => {
    const items = evaluateSetupReadiness(
      {
        auth_mode: "workos",
        needs_setup: false,
        wizard_dismissed: false,
        features: {},
        plans_seeded: true,
        bots: {
          telegram_username: null,
          discord_client_id: null,
          slack_workspace_url: null,
        },
        has_admin_account: true,
        registration_policy: "invite_only",
        deployment: {
          kind: "production",
          bills: true,
          local_code_sandbox: false,
          blob_store: "local",
          gaia_support: false,
          instance_toolkits: false,
          private_network_endpoints: false,
        },
        providers: {
          gemini: { configured: true, source: "stored", env_shadowed: false },
          tavily: { configured: false, source: "unset", env_shadowed: false },
        },
      },
      LLM_KEYS,
      3000,
    );
    expect(items.every((i) => i.configured)).toBe(true);
  });

  it("treats any configured provider as the provider lane being ready", () => {
    const items = evaluateSetupReadiness(
      {
        auth_mode: "local",
        needs_setup: false,
        wizard_dismissed: false,
        features: {},
        plans_seeded: true,
        bots: {
          telegram_username: null,
          discord_client_id: null,
          slack_workspace_url: null,
        },
        has_admin_account: true,
        registration_policy: "invite_only",
        deployment: {
          kind: "selfhost",
          bills: false,
          local_code_sandbox: false,
          blob_store: "local",
          gaia_support: false,
          instance_toolkits: true,
          private_network_endpoints: true,
        },
        providers: {
          ollama: { configured: true, source: "stored", env_shadowed: false },
          openrouter: {
            configured: false,
            source: "unset",
            env_shadowed: false,
          },
        },
      },
      LLM_KEYS,
      3000,
    );
    expect(
      items.find((i) => i.label === "LLM provider configured")?.configured,
    ).toBe(true);
  });

  it("does not count a tool-only key toward LLM readiness", () => {
    // A Tavily key alone leaves chat unusable — the server agrees
    // (_needs_setup counts only the four LLM lanes).
    const items = evaluateSetupReadiness(
      {
        auth_mode: "local",
        needs_setup: true,
        wizard_dismissed: false,
        features: {},
        plans_seeded: true,
        bots: {
          telegram_username: null,
          discord_client_id: null,
          slack_workspace_url: null,
        },
        has_admin_account: true,
        registration_policy: "invite_only",
        deployment: {
          kind: "selfhost",
          bills: false,
          local_code_sandbox: false,
          blob_store: "local",
          gaia_support: false,
          instance_toolkits: true,
          private_network_endpoints: true,
        },
        providers: {
          tavily: { configured: true, source: "stored", env_shadowed: false },
        },
      },
      LLM_KEYS,
      3000,
    );
    expect(
      items.find((i) => i.label === "LLM provider configured")?.configured,
    ).toBe(false);
  });

  it("never reports billing, which follows ENV and no setup step can enable", () => {
    const items = evaluateSetupReadiness(
      {
        auth_mode: "local",
        needs_setup: false,
        wizard_dismissed: false,
        features: {},
        plans_seeded: true,
        bots: {
          telegram_username: null,
          discord_client_id: null,
          slack_workspace_url: null,
        },
        has_admin_account: true,
        registration_policy: "invite_only",
        deployment: {
          kind: "selfhost",
          bills: false,
          local_code_sandbox: false,
          blob_store: "local",
          gaia_support: false,
          instance_toolkits: true,
          private_network_endpoints: true,
        },
        providers: {
          openrouter: {
            configured: true,
            source: "stored",
            env_shadowed: false,
          },
        },
      },
      LLM_KEYS,
      3000,
    );

    expect(items.find((i) => i.label === "billing enabled")).toBeUndefined();
    expect(items.every((i) => i.configured)).toBe(true);
  });

  it("does not warn about billing on a self-host instance that signs in with WorkOS", () => {
    const items = evaluateSetupReadiness(
      {
        auth_mode: "workos",
        needs_setup: false,
        wizard_dismissed: false,
        features: {},
        plans_seeded: false,
        bots: {
          telegram_username: null,
          discord_client_id: null,
          slack_workspace_url: null,
        },
        has_admin_account: true,
        registration_policy: "invite_only",
        deployment: {
          kind: "selfhost",
          bills: false,
          local_code_sandbox: false,
          blob_store: "local",
          gaia_support: false,
          instance_toolkits: true,
          private_network_endpoints: true,
        },
        providers: {
          openrouter: {
            configured: true,
            source: "stored",
            env_shadowed: false,
          },
        },
      },
      LLM_KEYS,
      3000,
    );

    expect(items.every((i) => i.configured)).toBe(true);
  });

  it("asks for seeded plans only where /setup/status says billing is on", () => {
    const status = {
      auth_mode: "local" as const,
      needs_setup: false,
      wizard_dismissed: false,
      features: {},
      plans_seeded: false,
      bots: {
        telegram_username: null,
        discord_client_id: null,
        slack_workspace_url: null,
      },
      has_admin_account: true,
      registration_policy: "invite_only" as const,
      deployment: {
        kind: "selfhost" as const,
        bills: false,
        local_code_sandbox: false,
        blob_store: "local" as const,
        gaia_support: false,
        instance_toolkits: true,
        private_network_endpoints: true,
      },
      providers: {
        openrouter: {
          configured: true,
          source: "stored" as const,
          env_shadowed: false,
        },
      },
    };

    const off = evaluateSetupReadiness(status, LLM_KEYS, 3000);
    const on = evaluateSetupReadiness(
      { ...status, deployment: { ...status.deployment, bills: true } },
      LLM_KEYS,
      3000,
    );

    expect(off.find((i) => i.label === "plans seeded")).toBeUndefined();
    expect(on.find((i) => i.label === "plans seeded")?.configured).toBe(false);
  });

  it("still reports other unconfigured items on a self-host instance", () => {
    const items = evaluateSetupReadiness(
      {
        auth_mode: "local",
        needs_setup: true,
        wizard_dismissed: false,
        features: {},
        plans_seeded: true,
        bots: {
          telegram_username: null,
          discord_client_id: null,
          slack_workspace_url: null,
        },
        has_admin_account: false,
        registration_policy: "invite_only",
        deployment: {
          kind: "selfhost",
          bills: false,
          local_code_sandbox: false,
          blob_store: "local",
          gaia_support: false,
          instance_toolkits: true,
          private_network_endpoints: true,
        },
        providers: {},
      },
      LLM_KEYS,
      3000,
    );

    // Billing is gone entirely; the remaining unconfigured items are intact.
    expect(items.find((i) => i.label === "billing enabled")).toBeUndefined();
    expect(items.filter((i) => !i.configured).map((i) => i.label)).toEqual([
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
  it("passes when Docker is usable", async () => {
    const result = await checkDockerDaemon("ready");

    expect(result.state).toBe("ok");
  });

  it("says Docker isn't installed when it isn't", async () => {
    const result = await checkDockerDaemon("not-installed");

    expect(result.state).toBe("fail");
    expect(result.severity).toBe("blocker");
    expect(result.detail).toBe("isn't installed");
  });

  it("tells a user the socket refuses to log out and in, not to start Docker", async () => {
    mockedExeca.mockResolvedValueOnce({
      stdout: "aryan sudo docker",
    } as Awaited<ResultPromise>);

    const result = await checkDockerDaemon("no-permission");

    expect(result.state).toBe("fail");
    expect(result.detail).toBe("is running, but your user can't use it yet");
    expect(result.fix).toContain("newgrp docker");
    expect(result.fix).not.toContain("systemctl start docker");
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

describe("checkBots", () => {
  it("reports nothing when no bot is enabled", async () => {
    expect(await checkBots([], "gaia-selfhost")).toEqual([]);
    expect(mockedExeca).not.toHaveBeenCalled();
  });

  it("warns per bot: healthy passes, a restarting or absent bot fails", async () => {
    const stdout = [
      "bot-telegram|running|Up 2 minutes (healthy)",
      "bot-discord|restarting|Restarting (1) 5 seconds ago",
    ].join("\n");
    mockedExeca.mockResolvedValueOnce({ stdout } as Awaited<ResultPromise>);

    const results = await checkBots(
      ["telegram", "discord", "slack"],
      "gaia-selfhost",
    );

    expect(results.map((r) => [r.id, r.state, r.severity])).toEqual([
      ["bot-telegram", "ok", "warning"],
      ["bot-discord", "fail", "warning"],
      ["bot-slack", "fail", "warning"],
    ]);
    expect(results[0]?.detail).toBe("running, healthy");
    expect(results[1]?.fix).toContain("logs bot-discord");
    expect(results[2]?.detail).toBe("not created");
  });

  it("passes a bot that is still connecting to its platform", async () => {
    mockedExeca.mockResolvedValueOnce({
      stdout: "bot-telegram|running|Up 5 seconds (health: starting)",
    } as Awaited<ResultPromise>);

    const [result] = await checkBots(["telegram"], "gaia-selfhost");

    expect(result?.state).toBe("ok");
    expect(result?.detail).toBe("running, health: starting");
  });

  it("fails a running bot whose healthcheck is failing", async () => {
    mockedExeca.mockResolvedValueOnce({
      stdout: "bot-slack|running|Up 3 minutes (unhealthy)",
    } as Awaited<ResultPromise>);

    const [result] = await checkBots(["slack"], "gaia-selfhost");

    expect(result?.state).toBe("fail");
    expect(result?.detail).toBe("running, unhealthy");
  });

  it("skips every bot when the daemon is down", async () => {
    mockedExeca.mockRejectedValueOnce(new Error("daemon down"));

    const results = await checkBots(["telegram"], "gaia-selfhost");

    expect(results.map((r) => r.state)).toEqual(["skipped"]);
  });
});

describe("unconfiguredInstallCheck", () => {
  it("names the checkout it inspected instead of sending the user to setup", () => {
    const result = unconfiguredInstallCheck("/home/me/gaia-src");

    expect(result.state).toBe("fail");
    expect(result.detail).toContain("/home/me/gaia-src");
    expect(result.detail).toContain("apps/api/.env");
    expect(result.fix).toContain("gaia up");
  });

  it("says no installation was found when there is no checkout at all", () => {
    const result = unconfiguredInstallCheck(null);

    expect(result.detail).toBe("isn't installed yet");
    expect(result.fix).toContain("gaia up");
  });
});

describe("checkApiHealth", () => {
  it("pings the API base it is given (the proxy origin on self-host)", async () => {
    stubFetch(async () => okResponse());

    const result = await checkApiHealth("http://localhost:3000/api/v1");

    expect(result.state).toBe("ok");
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe(
      "http://localhost:3000/api/v1/ping",
    );
  });

  it("fails on error status codes", async () => {
    stubFetch(async () => ({ ok: false, status: 502, json: async () => ({}) }));

    const result = await checkApiHealth("http://localhost:3000/api/v1");

    expect(result.state).toBe("fail");
    expect(result.detail).toContain("502");
  });

  it("fails on connection errors with a start hint", async () => {
    stubFetch(async () => {
      throw new Error("ECONNREFUSED");
    });

    const result = await checkApiHealth("http://localhost:3000/api/v1");

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

describe("printDoctorReport", () => {
  it("starts every check's label in the same column, whatever its status", () => {
    const write = vi
      .spyOn(process.stdout, "write")
      .mockImplementation(() => true);
    const result = (
      state: CheckResult["state"],
      severity: CheckResult["severity"],
    ): CheckResult => ({ id: "x", label: "Label", severity, state });

    printDoctorReport({
      install: "/srv/gaia (self-host)",
      installed: true,
      results: [
        result("ok", "blocker"),
        result("fail", "warning"),
        result("fail", "blocker"),
      ],
    });

    const lines = write.mock.calls
      .map(([chunk]) => stripVTControlCharacters(String(chunk)))
      .filter((line) => line.includes("Label"));
    write.mockRestore();
    expect(lines.map((line) => line.indexOf("Label"))).toEqual(
      Array(3).fill(lines[0]?.indexOf("Label")),
    );
    for (const line of lines) expect(line).toMatch(/^ {2}\S Label/);
  });

  // cli-audit 04: no Docker printed four skip rows and two "start the stack" fixes.
  it("collapses checks skipped for one cause into one line, with no fix", () => {
    let text = "";
    const write = vi.spyOn(process.stdout, "write").mockImplementation((c) => {
      text += String(c);
      return true;
    });
    const skipped = (label: string): CheckResult => ({
      label,
      severity: "blocker",
      state: "skipped",
      detail: "they need Docker",
      fix: "never shown",
    });

    printDoctorReport({
      install: "/srv/gaia (self-host)",
      installed: true,
      results: [
        {
          label: "Docker",
          severity: "blocker",
          state: "fail",
          detail: "Docker isn't installed",
          fix: "Run 'gaia up'",
        },
        skipped("Ports"),
        skipped("Containers"),
        skipped("Disk space"),
      ],
    });
    write.mockRestore();

    expect(text).toContain(
      "Not checked: Ports, Containers, Disk space (they need Docker)",
    );
    expect(text.match(/Run 'gaia up'/g)).toHaveLength(1);
    expect(text).not.toContain("never shown");
    expect(text).toContain("1 problem");
  });

  it("says a fix shared by consecutive problems once, under the last of them", () => {
    let text = "";
    const write = vi.spyOn(process.stdout, "write").mockImplementation((c) => {
      text += String(c);
      return true;
    });
    const fix = "Run 'gaia up': it installs everything GAIA needs.";

    printDoctorReport({
      install: "GAIA isn't installed yet",
      installed: false,
      results: [
        { label: "Docker", severity: "blocker", state: "fail", fix },
        { label: "GAIA", severity: "blocker", state: "fail", fix },
      ],
    });
    write.mockRestore();

    expect(text.split(fix)).toHaveLength(2);
    expect(text.indexOf(fix)).toBeGreaterThan(text.indexOf("GAIA "));
  });
});

describe("checkSetupReadiness", () => {
  it("says what is missing in plain words", async () => {
    stubSetupEndpoints({
      auth_mode: "local",
      needs_setup: true,
      wizard_dismissed: false,
      features: {},
      plans_seeded: false,
      bots: {
        telegram_username: null,
        discord_client_id: null,
        slack_workspace_url: null,
      },
      has_admin_account: false,
      registration_policy: "invite_only",
      deployment: {
        kind: "selfhost",
        bills: false,
        local_code_sandbox: false,
        blob_store: "local",
        gaia_support: false,
        instance_toolkits: true,
        private_network_endpoints: true,
      },
      providers: {
        openai: { configured: true, source: "env", env_shadowed: false },
      },
    });

    const results = await checkSetupReadiness({
      apiHealthy: true,
      apiUrl: "http://localhost:3000/api/v1",
      webPort: 3000,
    });

    expect(results.map((r) => [r.label, r.detail])).toEqual([
      ["Setup", "not finished: no admin account yet"],
    ]);
  });

  it("reports what the wizard still owes as one warning with one fix", async () => {
    stubSetupEndpoints({
      auth_mode: "workos",
      needs_setup: true,
      wizard_dismissed: false,
      features: {},
      plans_seeded: false,
      bots: {
        telegram_username: null,
        discord_client_id: null,
        slack_workspace_url: null,
      },
      has_admin_account: true,
      registration_policy: "invite_only",
      deployment: {
        kind: "selfhost",
        bills: false,
        local_code_sandbox: false,
        blob_store: "local",
        gaia_support: false,
        instance_toolkits: true,
        private_network_endpoints: true,
      },
      providers: {},
    });

    const results = await checkSetupReadiness({
      apiHealthy: true,
      apiUrl: "http://localhost:3000/api/v1",
      webPort: 3000,
    });

    expect(results).toHaveLength(1); // provider lane
    expect(vi.mocked(fetch).mock.calls[0]?.[0]).toBe(
      "http://localhost:3000/api/v1/setup/status",
    );
    for (const result of results) {
      expect(result.severity).toBe("warning");
      expect(result.state).toBe("fail");
      expect(result.fix).toContain("/setup in your browser");
    }
  });

  it("passes once every setup item is configured", async () => {
    stubSetupEndpoints({
      auth_mode: "workos",
      needs_setup: false,
      wizard_dismissed: false,
      features: {},
      plans_seeded: true,
      bots: {
        telegram_username: null,
        discord_client_id: null,
        slack_workspace_url: null,
      },
      has_admin_account: true,
      registration_policy: "invite_only",
      deployment: {
        kind: "production",
        bills: true,
        local_code_sandbox: false,
        blob_store: "local",
        gaia_support: false,
        instance_toolkits: false,
        private_network_endpoints: false,
      },
      providers: {
        openrouter: { configured: true, source: "stored", env_shadowed: false },
      },
    });

    const results = await checkSetupReadiness({
      apiHealthy: true,
      apiUrl: "http://localhost:3000/api/v1",
      webPort: 3000,
    });

    expect(results).toHaveLength(1);
    expect(results[0]?.state).toBe("ok");
  });

  it("reports ok on a self-host instance with billing disabled", async () => {
    // Every self-host install once showed a permanent "[warn] Billing enabled
    // is not configured": billing follows ENV, which no setup step changes.
    stubSetupEndpoints({
      auth_mode: "local",
      needs_setup: false,
      wizard_dismissed: false,
      features: {},
      plans_seeded: true,
      bots: {
        telegram_username: null,
        discord_client_id: null,
        slack_workspace_url: null,
      },
      has_admin_account: true,
      registration_policy: "invite_only",
      deployment: {
        kind: "selfhost",
        bills: false,
        local_code_sandbox: false,
        blob_store: "local",
        gaia_support: false,
        instance_toolkits: true,
        private_network_endpoints: true,
      },
      providers: {
        openrouter: { configured: true, source: "stored", env_shadowed: false },
      },
    });

    const results = await checkSetupReadiness({
      apiHealthy: true,
      apiUrl: "http://localhost:3000/api/v1",
      webPort: 3000,
    });

    expect(results).toHaveLength(1);
    expect(results[0]?.state).toBe("ok");
    expect(results[0]?.label).toBe("Setup");
  });

  it("counts an OpenAI-only instance as LLM-ready per the served catalog", async () => {
    stubSetupEndpoints({
      auth_mode: "local",
      needs_setup: false,
      wizard_dismissed: false,
      features: {},
      plans_seeded: true,
      bots: {
        telegram_username: null,
        discord_client_id: null,
        slack_workspace_url: null,
      },
      has_admin_account: true,
      registration_policy: "invite_only",
      deployment: {
        kind: "selfhost",
        bills: false,
        local_code_sandbox: false,
        blob_store: "local",
        gaia_support: false,
        instance_toolkits: true,
        private_network_endpoints: true,
      },
      providers: {
        openai: { configured: true, source: "stored", env_shadowed: false },
      },
    });

    const results = await checkSetupReadiness({
      apiHealthy: true,
      apiUrl: "http://localhost:3000/api/v1",
      webPort: 3000,
    });

    expect(results.map((r) => r.state)).toEqual(["ok"]);
  });

  it("skips naming the catalog endpoint when it cannot be read", async () => {
    stubFetch(async (url) =>
      url.endsWith("/catalog")
        ? { ok: false, status: 404, json: async () => ({}) }
        : okResponse({ providers: {} }),
    );

    const results = await checkSetupReadiness({
      apiHealthy: true,
      apiUrl: "http://localhost:3000/api/v1",
      webPort: 3000,
    });

    expect(results).toEqual([
      expect.objectContaining({
        state: "skipped",
        detail: "HTTP 404 from /api/v1/setup/catalog",
      }),
    ]);
  });

  it("skips when the API health check already failed", async () => {
    const results = await checkSetupReadiness({
      apiHealthy: false,
      apiUrl: "http://localhost:3000/api/v1",
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
    expect(
      hasBlockingFailure({
        install: "",
        installed: true,
        results: [makeResult(overrides)],
      }),
    ).toBe(expected);
  });
});
