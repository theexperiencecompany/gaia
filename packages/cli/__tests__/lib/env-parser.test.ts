import { describe, expect, it } from "vitest";
import type { EnvCategory, EnvVar } from "../../src/lib/env-parser.js";
import {
  applyModeDefaults,
  applyPortOverrides,
  getAlternativeGroups,
  getCoreVariables,
  getDefaultValue,
  getDeploymentDefaults,
  getDeploymentVariables,
  getInfrastructureVariables,
  getWebInfrastructureDefaults,
  isCategorySatisfied,
} from "../../src/lib/env-parser.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function makeVar(overrides?: Partial<EnvVar>): EnvVar {
  return {
    name: "TEST_VAR",
    required: true,
    category: "Test",
    description: "A test variable",
    affectedFeatures: "testing",
    ...overrides,
  };
}

function makeCategory(overrides?: Partial<EnvCategory>): EnvCategory {
  return {
    name: "Test Category",
    description: "A test category",
    affectedFeatures: "testing",
    requiredInProd: false,
    allRequired: false,
    variables: [makeVar()],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// getDefaultValue
// ---------------------------------------------------------------------------
describe("getDefaultValue", () => {
  it("returns selfhost defaults for infrastructure vars", () => {
    expect(getDefaultValue("MONGO_DB", "selfhost")).toBe(
      "mongodb://mongo:27017/gaia",
    );
    expect(getDefaultValue("REDIS_URL", "selfhost")).toBe("redis://redis:6379");
    expect(getDefaultValue("CHROMADB_HOST", "selfhost")).toBe("chromadb");
  });

  it("returns developer defaults for infrastructure vars", () => {
    expect(getDefaultValue("MONGO_DB", "developer")).toBe(
      "mongodb://localhost:27017/gaia",
    );
    expect(getDefaultValue("REDIS_URL", "developer")).toBe(
      "redis://localhost:6379",
    );
    expect(getDefaultValue("CHROMADB_HOST", "developer")).toBe("localhost");
  });

  it("returns deployment defaults", () => {
    expect(getDefaultValue("HOST", "selfhost")).toBe("http://localhost:8000");
    expect(getDefaultValue("FRONTEND_URL", "developer")).toBe(
      "http://localhost:3000",
    );
    expect(getDefaultValue("SETUP_MODE", "selfhost")).toBe("selfhost");
    expect(getDefaultValue("SETUP_MODE", "developer")).toBe("developer");
  });

  it("returns undefined for unknown variables", () => {
    expect(getDefaultValue("TOTALLY_UNKNOWN_VAR", "selfhost")).toBeUndefined();
    expect(getDefaultValue("TOTALLY_UNKNOWN_VAR", "developer")).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// applyPortOverrides
// ---------------------------------------------------------------------------
describe("applyPortOverrides", () => {
  it("replaces bare port values", () => {
    const env = { CHROMADB_PORT: "8080" };
    applyPortOverrides(env, { 8080: 9090 });
    expect(env.CHROMADB_PORT).toBe("9090");
  });

  it("replaces port in URL context", () => {
    const env = {
      POSTGRES_URL: "postgresql://postgres:postgres@localhost:5432/postgres", // pragma: allowlist secret
    };
    applyPortOverrides(env, { 5432: 5433 });
    expect(env.POSTGRES_URL).toBe(
      "postgresql://postgres:postgres@localhost:5433/postgres", // pragma: allowlist secret
    );
  });

  it("skips infrastructure keys in selfhost mode", () => {
    const env = {
      MONGO_DB: "mongodb://mongo:27017/gaia",
      HOST: "http://localhost:8000",
    };
    applyPortOverrides(env, { 27017: 27018, 8000: 9000 }, "selfhost");
    // MONGO_DB is infrastructure — should be untouched
    expect(env.MONGO_DB).toBe("mongodb://mongo:27017/gaia");
    // HOST is deployment — should be updated
    expect(env.HOST).toBe("http://localhost:9000");
  });

  it("handles multiple overrides simultaneously", () => {
    const env = {
      A: "http://localhost:3000/app",
      B: "http://localhost:8000/api",
    };
    applyPortOverrides(env, { 3000: 3001, 8000: 8001 });
    expect(env.A).toBe("http://localhost:3001/app");
    expect(env.B).toBe("http://localhost:8001/api");
  });
});

// ---------------------------------------------------------------------------
// getCoreVariables
// ---------------------------------------------------------------------------
describe("getCoreVariables", () => {
  it("extracts vars from core category names", () => {
    const mongoVar = makeVar({
      name: "MONGO_DB",
      category: "MongoDB Connection",
    });
    const redisVar = makeVar({
      name: "REDIS_URL",
      category: "Redis Connection",
    });
    const categories = [
      makeCategory({ name: "MongoDB Connection", variables: [mongoVar] }),
      makeCategory({ name: "Redis Connection", variables: [redisVar] }),
    ];

    const result = getCoreVariables(categories);

    expect(result).toHaveLength(2);
    expect(result.map((v) => v.name)).toEqual(["MONGO_DB", "REDIS_URL"]);
  });

  it("ignores non-core categories", () => {
    const categories = [
      makeCategory({ name: "Some Other Service", variables: [makeVar()] }),
      makeCategory({ name: "Custom Stuff", variables: [makeVar()] }),
    ];

    const result = getCoreVariables(categories);

    expect(result).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// applyModeDefaults
// ---------------------------------------------------------------------------
describe("applyModeDefaults", () => {
  it("applies mode-specific defaults to variables", () => {
    const categories = [
      makeCategory({
        variables: [makeVar({ name: "MONGO_DB" })],
      }),
    ];

    const result = applyModeDefaults(categories, "developer");

    expect(result[0]?.variables[0]?.defaultValue).toBe(
      "mongodb://localhost:27017/gaia",
    );
  });

  it("preserves existing defaults when no mode default exists", () => {
    const categories = [
      makeCategory({
        variables: [makeVar({ name: "UNKNOWN_VAR", defaultValue: "keep-me" })],
      }),
    ];

    const result = applyModeDefaults(categories, "selfhost");

    expect(result[0]?.variables[0]?.defaultValue).toBe("keep-me");
  });
});

// ---------------------------------------------------------------------------
// getInfrastructureVariables / getDeploymentVariables
// ---------------------------------------------------------------------------
describe("getInfrastructureVariables", () => {
  it("returns correct variable names", () => {
    const vars = getInfrastructureVariables();
    expect(vars).toContain("MONGO_DB");
    expect(vars).toContain("REDIS_URL");
    expect(vars).toContain("POSTGRES_URL");
    expect(vars).toContain("CHROMADB_HOST");
    expect(vars).toContain("CHROMADB_PORT");
    expect(vars).toContain("RABBITMQ_URL");
    expect(vars).toHaveLength(6);
  });
});

describe("getDeploymentVariables", () => {
  it("returns correct variable names", () => {
    const vars = getDeploymentVariables();
    expect(vars).toContain("HOST");
    expect(vars).toContain("FRONTEND_URL");
    expect(vars).toContain("GAIA_BACKEND_URL");
    expect(vars).toContain("SETUP_MODE");
    expect(vars).toHaveLength(4);
  });
});

// ---------------------------------------------------------------------------
// getDeploymentDefaults
// ---------------------------------------------------------------------------
describe("getDeploymentDefaults", () => {
  it("returns a copy, not a reference, for each mode", () => {
    const defaults1 = getDeploymentDefaults("selfhost");
    const defaults2 = getDeploymentDefaults("selfhost");

    // Equal values
    expect(defaults1).toEqual(defaults2);

    // But not the same object
    defaults1.HOST = "mutated";
    expect(defaults2.HOST).not.toBe("mutated");
  });

  it("returns selfhost deployment defaults", () => {
    const defaults = getDeploymentDefaults("selfhost");
    expect(defaults.SETUP_MODE).toBe("selfhost");
    expect(defaults.GAIA_BACKEND_URL).toBe("http://gaia-backend:80"); // NOSONAR — internal Docker network URL, not a public endpoint
  });

  it("returns developer deployment defaults", () => {
    const defaults = getDeploymentDefaults("developer");
    expect(defaults.SETUP_MODE).toBe("developer");
    expect(defaults.GAIA_BACKEND_URL).toBe("http://host.docker.internal:8000"); // NOSONAR — internal Docker network URL, not a public endpoint
  });
});

// ---------------------------------------------------------------------------
// getAlternativeGroups
// ---------------------------------------------------------------------------
describe("getAlternativeGroups", () => {
  it("extracts alternativeGroup mapping", () => {
    const categories = [
      makeCategory({ name: "OpenAI", alternativeGroup: "Anthropic" }),
      makeCategory({ name: "Anthropic", alternativeGroup: "OpenAI" }),
    ];

    const result = getAlternativeGroups(categories);

    expect(result.get("OpenAI")).toBe("Anthropic");
    expect(result.get("Anthropic")).toBe("OpenAI");
  });

  it("ignores categories without alternativeGroup", () => {
    const categories = [
      makeCategory({ name: "Redis Connection" }),
      makeCategory({ name: "OpenAI", alternativeGroup: "Anthropic" }),
    ];

    const result = getAlternativeGroups(categories);

    expect(result.size).toBe(1);
    expect(result.has("Redis Connection")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isCategorySatisfied
// ---------------------------------------------------------------------------
describe("isCategorySatisfied", () => {
  it("returns true if category is in configured set", () => {
    const configured = new Set(["OpenAI"]);
    const alternatives = new Map<string, string>();

    expect(isCategorySatisfied("OpenAI", configured, alternatives)).toBe(true);
  });

  it("returns true if alternative is configured", () => {
    const configured = new Set(["Anthropic"]);
    const alternatives = new Map([["OpenAI", "Anthropic"]]);

    expect(isCategorySatisfied("OpenAI", configured, alternatives)).toBe(true);
  });

  it("returns false if neither configured nor alternative", () => {
    const configured = new Set(["Redis Connection"]);
    const alternatives = new Map([["OpenAI", "Anthropic"]]);

    expect(isCategorySatisfied("OpenAI", configured, alternatives)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// getWebInfrastructureDefaults
// ---------------------------------------------------------------------------
describe("getWebInfrastructureDefaults", () => {
  it("returns API URL with default port 8000", () => {
    const defaults = getWebInfrastructureDefaults("selfhost");

    expect(defaults.NEXT_PUBLIC_API_BASE_URL).toBe(
      "http://localhost:8000/api/v1/",
    );
  });

  it("returns API URL with custom port override", () => {
    const defaults = getWebInfrastructureDefaults("developer", { 8000: 9000 });

    expect(defaults.NEXT_PUBLIC_API_BASE_URL).toBe(
      "http://localhost:9000/api/v1/",
    );
  });
});
