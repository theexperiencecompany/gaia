/**
 * The setup wizard and local auth call `<api base>/setup/*` and
 * `<api base>/auth/*`. Joining by string onto `apiauth.getUri()` dropped the
 * separator (the base has no trailing slash), so every call went to
 * `…/api/v1setup/status` and 404'd — on a same-origin base it even doubled up
 * as `/api/v1/api/v1setup/status`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiauth, apiBaseUrl } from "@/lib/api/client";
import { localAuthApi } from "@/lib/api/localAuth";
import { setupTransport } from "@/lib/api/setupTransport";

afterEach(() => {
  vi.restoreAllMocks();
});

/** The URL axios would request for the url argument of the first call. */
function requestedUrl(spy: { mock: { calls: unknown[][] } }): string {
  const url = spy.mock.calls[0]?.[0] as string;
  return apiauth.getUri({ url });
}

describe("setup and local-auth transport URLs", () => {
  it("puts /setup under the API base", async () => {
    const spy = vi.spyOn(apiauth, "get").mockResolvedValue({ data: {} });

    await setupTransport.get("status");

    expect(requestedUrl(spy)).toBe(`${apiBaseUrl}/setup/status`);
  });

  it("puts /auth under the API base", async () => {
    const spy = vi.spyOn(apiauth, "post").mockResolvedValue({ data: {} });

    await localAuthApi.login("a@example.com", "x", { silent: true });

    expect(requestedUrl(spy)).toBe(`${apiBaseUrl}/auth/login`);
  });
});
