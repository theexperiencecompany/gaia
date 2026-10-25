/**
 * The setup wizard and local auth call `<api base>/setup/*` and
 * `<api base>/auth/*`. Joining by string onto `apiauth.getUri()` dropped the
 * separator (the base has no trailing slash), so every call went to
 * `…/api/v1setup/status` and 404'd — on a same-origin base it even doubled up
 * as `/api/v1/api/v1setup/status`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { authApi } from "@/features/auth/api/authApi";
import { providersApi } from "@/features/settings/api/providersApi";
import { apiauth, apiOrigin } from "@/lib/api/client";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("setup and local-auth transport URLs", () => {
  it("reads setup status through the typed client at /setup/status", async () => {
    const spy = vi
      .spyOn(apiauth, "request")
      .mockResolvedValue({ status: 200, data: {}, headers: {} });

    await providersApi.fetchSetupStatus();

    expect(spy.mock.calls[0]?.[0]?.url).toBe(
      `${apiOrigin}/api/v1/setup/status`,
    );
  });

  it("signs in through the typed client at /auth/login", async () => {
    const spy = vi
      .spyOn(apiauth, "request")
      .mockResolvedValue({ status: 200, data: { user: {} }, headers: {} });

    await authApi.localLogin("a@example.com", "x");

    const config = spy.mock.calls[0]?.[0];
    expect(config?.method).toBe("POST");
    expect(config?.url).toBe(`${apiOrigin}/api/v1/auth/login`);
  });
});
