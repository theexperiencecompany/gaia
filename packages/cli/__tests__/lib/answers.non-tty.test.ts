import { beforeEach, describe, expect, it, vi } from "vitest";
import { createUpAnswerResolver } from "../../src/lib/answers.js";
import { readConfig } from "../../src/lib/config.js";

// Simulate a schema that marks OPENROUTER_API_KEY required and a world where
// no infrastructure defaults resolve — isolating the resolver's fail-loud
// branch (non-TTY + required + hinted + unresolved) which today's real
// vendored data cannot reach (MONGO/REDIS always resolve from defaults).
vi.mock("../../src/lib/env-parser.js", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../../src/lib/env-parser.js")>();
  return {
    ...actual,
    getDefaultValue: () => undefined,
    getInfrastructureVariables: () => [],
    loadVendoredSchema: () => [
      {
        name: "Simulated Required Secret",
        description: "",
        affectedFeatures: "",
        requiredInProd: true,
        allRequired: true,
        variables: [
          {
            name: "OPENROUTER_API_KEY",
            required: true,
            category: "Simulated Required Secret",
            description: "",
            affectedFeatures: "",
          },
          {
            name: "MYSTERY_REQUIRED",
            required: true,
            category: "Simulated Required Secret",
            description: "",
            affectedFeatures: "",
          },
        ],
      },
    ],
  };
});

vi.mock("../../src/lib/config.js", () => ({
  readConfig: vi.fn(() => null),
  updateConfig: vi.fn(),
  writeConfig: vi.fn(),
}));

const mockedReadConfig = vi.mocked(readConfig);

beforeEach(() => {
  mockedReadConfig.mockClear();
  mockedReadConfig.mockReturnValue(null);
});

describe("createUpAnswerResolver fail-loud (non-TTY, simulated required secret)", () => {
  const makeResolver = (interactive: boolean) =>
    createUpAnswerResolver({
      flags: {},
      repoPath: "/tmp/gaia-target",
      interactive,
    });

  it("throws naming the providing flag when unresolved in non-TTY", () => {
    expect(() =>
      makeResolver(false)("env_var", { varName: "OPENROUTER_API_KEY" }),
    ).toThrow(/--llm-key --llm-provider openrouter/);
  });

  it("does not throw interactively — returns skip value instead", () => {
    expect(
      makeResolver(true)("env_var", { varName: "OPENROUTER_API_KEY" }),
    ).toBe("");
  });

  it("throws with generic guidance for required vars without a flag hint", () => {
    // No hint exists for this name; the message must still fail loud rather
    // than silently defaulting.
    expect(() =>
      makeResolver(false)("env_var", { varName: "MYSTERY_REQUIRED" }),
    ).toThrow(/required but could not be resolved/);
  });

  it("returns '' for hinted secrets without provider intent (wizard owns them)", () => {
    // GOOGLE_API_KEY has a hint but no required flag in this fixture and no
    // provider intent in flags — skipped, never silently defaulted.
    expect(makeResolver(false)("env_var", { varName: "GOOGLE_API_KEY" })).toBe(
      "",
    );
  });
});
