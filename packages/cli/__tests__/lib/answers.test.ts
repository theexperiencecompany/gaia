import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createUpAnswerResolver,
  portOverridesFromFlags,
} from "../../src/lib/answers.js";
import { readConfig } from "../../src/lib/config.js";

vi.mock("../../src/lib/config.js", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  readConfig: vi.fn(),
  updateConfig: vi.fn(),
  writeConfig: vi.fn(),
}));

const mockedReadConfig = vi.mocked(readConfig);

beforeEach(() => {
  mockedReadConfig.mockReset();
  mockedReadConfig.mockReturnValue(null);
});

function makeResolver(opts?: {
  interactive?: boolean;
  savedValues?: Record<string, string>;
}) {
  return createUpAnswerResolver({
    repoPath: "/tmp/gaia-target",
    interactive: opts?.interactive ?? true,
  });
}

describe("portOverridesFromFlags", () => {
  it("maps the web port to the proxy's default port", () => {
    expect(portOverridesFromFlags({ webPort: 4000 })).toEqual({ 3000: 4000 });
  });

  it("moves the proxy to 80/443 for a domain", () => {
    expect(portOverridesFromFlags({ domain: "gaia.example.com" })).toEqual({
      3000: 80,
      3443: 443,
    });
  });

  it("returns empty overrides without flags", () => {
    expect(portOverridesFromFlags({})).toEqual({});
  });
});

describe("createUpAnswerResolver precedence", () => {
  it("resolves env vars from saved config values first", () => {
    mockedReadConfig.mockReturnValue(
      makeConfig({
        values: { TAVILY_API_KEY: "saved-tavily" },
      }),
    );
    const resolve = makeResolver();

    expect(resolve("env_var", { varName: "TAVILY_API_KEY" })).toBe(
      "saved-tavily",
    );
  });

  it("falls back to mode defaults last (deployment vars resolve; infra is pre-applied)", () => {
    const resolve = makeResolver();
    // Deployment var: resolved from DEPLOYMENT_DEFAULTS via the defaults tier.
    expect(resolve("env_var", { varName: "GAIA_BACKEND_URL" })).toBe(
      "http://gaia-backend:8000",
    );
    // Infra vars never reach the chain — they're answered as skip because
    // runEnvSetup pre-applies INFRASTRUCTURE_DEFAULTS before prompting.
    expect(resolve("env_var", { varName: "MONGO_DB" })).toBe("");
  });

  it("answers flow-control prompt ids so up never blocks", () => {
    const resolve = makeResolver();
    expect(resolve("setup_mode")).toBe("selfhost");
    expect(resolve("env_method")).toBe("manual");
    expect(resolve("repo_path")).toBe("/tmp/gaia-target");
    expect(resolve("existing_repo")).toBe("use_existing");
    expect(resolve("port_conflicts")).toBe("accept");
    expect(resolve("env_group")).toEqual({});
    // Unknown ids fall through to interactive/plain handling.
    expect(resolve("docker_install_confirm")).toBeUndefined();
    expect(resolve("exit")).toBeUndefined();
  });

  it("skips infrastructure vars in per-var answers (pre-applied)", () => {
    const resolve = makeResolver();
    expect(resolve("env_var", { varName: "POSTGRES_URL" })).toBe("");
  });

  it("returns '' for unknown optional vars instead of blocking", () => {
    const resolve = makeResolver();
    expect(resolve("env_var", { varName: "SOME_RANDOM_VAR" })).toBe("");
  });

  it("does not throw for schema-required vars that resolve from defaults", () => {
    // MONGO_DB is the only schema-required family today and always resolves
    // at the defaults layer — never throws, even non-interactively.
    const resolve = makeResolver({ interactive: false });
    expect(() => resolve("env_var", { varName: "MONGO_DB" })).not.toThrow();
  });
});

function makeConfig(overrides: object) {
  return {
    version: "test",
    setupComplete: false,
    setupMethod: "manual" as const,
    repoPath: "",
    createdAt: "",
    updatedAt: "",
    ...overrides,
  };
}
