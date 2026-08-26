import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createUpAnswerResolver,
  PROVIDER_ENV_VAR,
  portOverridesFromFlags,
  type UpFlags,
  validateLlmFlags,
} from "../../src/lib/answers.js";
import { readConfig } from "../../src/lib/config.js";

vi.mock("../../src/lib/config.js", () => ({
  readConfig: vi.fn(),
  updateConfig: vi.fn(),
  writeConfig: vi.fn(),
}));

const mockedReadConfig = vi.mocked(readConfig);

beforeEach(() => {
  mockedReadConfig.mockReset();
  mockedReadConfig.mockReturnValue(null);
});

function makeResolver(
  flags: UpFlags,
  opts?: {
    interactive?: boolean;
    savedValues?: Record<string, string>;
  },
) {
  return createUpAnswerResolver({
    flags,
    repoPath: "/tmp/gaia-target",
    interactive: opts?.interactive ?? true,
  });
}

describe("validateLlmFlags", () => {
  it("accepts a complete openrouter pair", () => {
    expect(() =>
      validateLlmFlags({ llmKey: "sk", llmProvider: "openrouter" }),
    ).not.toThrow();
  });

  it("fails loud naming --llm-provider when only the key is given", () => {
    expect(() => validateLlmFlags({ llmKey: "sk" })).toThrow(/--llm-provider/);
  });

  it("fails loud naming --llm-key when only the provider is given", () => {
    expect(() => validateLlmFlags({ llmProvider: "openrouter" })).toThrow(
      /--llm-key/,
    );
  });

  it("rejects a key with the runtime-configured custom provider", () => {
    expect(() =>
      validateLlmFlags({ llmKey: "sk", llmProvider: "custom" }),
    ).toThrow(/--llm-key is not used/);
  });

  it("allows bare custom provider (wizard configures it)", () => {
    expect(() => validateLlmFlags({ llmProvider: "custom" })).not.toThrow();
  });
});

describe("portOverridesFromFlags", () => {
  it("maps api/web ports to their service ports", () => {
    expect(portOverridesFromFlags({ apiPort: 9000, webPort: 4000 })).toEqual({
      8000: 9000,
      3000: 4000,
    });
  });

  it("returns empty overrides without flags", () => {
    expect(portOverridesFromFlags({})).toEqual({});
  });
});

describe("createUpAnswerResolver precedence", () => {
  it("resolves env vars: CLI flags beat saved values and defaults", () => {
    mockedReadConfig.mockReturnValue(
      makeConfig({
        values: { OPENROUTER_API_KEY: "saved-key" },
      }),
    );
    const resolve = makeResolver({
      llmKey: "flag-key",
      llmProvider: "openrouter",
    });

    const answer = resolve("env_alternatives") as {
      selectedGroups: string[];
      values: Record<string, string>;
    };
    expect(answer.values.OPENROUTER_API_KEY).toBe("flag-key");
    // And per-var resolution agrees:
    expect(resolve("env_var", { varName: PROVIDER_ENV_VAR.openrouter })).toBe(
      "flag-key",
    );
  });

  it("falls back to saved config values when no flag applies", () => {
    mockedReadConfig.mockReturnValue(
      makeConfig({
        values: { TAVILY_API_KEY: "saved-tavily" },
      }),
    );
    const resolve = makeResolver({});

    expect(resolve("env_var", { varName: "TAVILY_API_KEY" })).toBe(
      "saved-tavily",
    );
  });

  it("falls back to mode defaults last (deployment vars resolve; infra is pre-applied)", () => {
    const resolve = makeResolver({});
    // Deployment var: resolved from DEPLOYMENT_DEFAULTS via the defaults tier.
    expect(resolve("env_var", { varName: "GAIA_BACKEND_URL" })).toBe(
      "http://gaia-backend:80",
    );
    // Infra vars never reach the chain — they're answered as skip because
    // runEnvSetup pre-applies INFRASTRUCTURE_DEFAULTS before prompting.
    expect(resolve("env_var", { varName: "MONGO_DB" })).toBe("");
  });

  it("answers flow-control prompt ids so up never blocks", () => {
    const resolve = makeResolver({});
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
    const resolve = makeResolver({});
    expect(resolve("env_var", { varName: "POSTGRES_URL" })).toBe("");
  });

  it("returns '' for unknown optional vars instead of blocking", () => {
    const resolve = makeResolver({});
    expect(resolve("env_var", { varName: "SOME_RANDOM_VAR" })).toBe("");
  });

  it("does not throw for schema-required vars that resolve from defaults", () => {
    // MONGO_DB is the only schema-required family today and always resolves
    // at the defaults layer — never throws, even non-interactively.
    const resolve = makeResolver({}, { interactive: false });
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
