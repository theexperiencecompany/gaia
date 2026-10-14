import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { login } = vi.hoisted(() => ({ login: vi.fn() }));
vi.mock("@infisical/sdk", () => ({
  InfisicalSDK: vi.fn().mockImplementation(() => ({
    auth: () => ({ universalAuth: { login } }),
    secrets: () => ({
      listSecrets: vi.fn().mockResolvedValue({ secrets: [] }),
    }),
  })),
}));

import { injectInfisicalSecrets } from "@gaia/shared/bots";

const INFISICAL_ENV = {
  INFISICAL_PROJECT_ID: "project",
  INFISICAL_MACHINE_IDENTITY_CLIENT_ID: "client",
  INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET: "secret", // pragma: allowlist secret
};

describe("injectInfisicalSecrets on a self-hosted instance", () => {
  beforeEach(() => {
    login.mockReset();
    vi.stubEnv("NODE_ENV", "production");
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("boots without Infisical even though the image is production", async () => {
    vi.stubEnv("ENV", "selfhost");

    await expect(injectInfisicalSecrets()).resolves.toBeUndefined();
  });

  it("never contacts Infisical, even with identity vars present", async () => {
    vi.stubEnv("ENV", "selfhost");
    for (const [key, value] of Object.entries(INFISICAL_ENV)) {
      vi.stubEnv(key, value);
    }

    await injectInfisicalSecrets();

    expect(login).not.toHaveBeenCalled();
  });

  it("still requires Infisical in production", async () => {
    vi.stubEnv("ENV", "production");

    await expect(injectInfisicalSecrets()).rejects.toThrow(
      "Infisical is required in production",
    );
  });
});
