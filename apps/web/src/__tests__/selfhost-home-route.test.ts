import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Outside a Next request scope connection() throws; the page's render is not under test.
vi.mock("next/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/server")>()),
  connection: async () => undefined,
}));

import { selfhostHomeRedirect } from "@/features/auth/api/selfhostHomeRedirect";
import { resolveInstanceAuthMode } from "@/features/auth/api/serverSetupStatusApi";

const SETUP_STATUS = {
  auth_mode: "local",
  has_admin_account: true,
  registration_policy: "invite_only",
  needs_setup: false,
  wizard_dismissed: false,
  deployment: {
    kind: "selfhost",
    bills: false,
    local_code_sandbox: false,
    blob_store: "local",
    gaia_support: false,
  },
  providers: {},
  plans_seeded: false,
  bots: {
    telegram_username: null,
    discord_client_id: null,
    slack_workspace_url: null,
  },
};

function stubSetupStatus(overrides: Partial<typeof SETUP_STATUS> = {}) {
  const fetchMock = vi.fn(
    async () =>
      new Response(JSON.stringify({ ...SETUP_STATUS, ...overrides }), {
        status: 200,
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Where "/" sends this request, or null when it renders in place. */
async function homeTarget(cookie?: string): Promise<string | null> {
  const request = new NextRequest("http://gaia.test/", {
    headers: cookie ? { cookie } : {},
  });
  const response = await selfhostHomeRedirect(request);
  const location = response?.headers.get("location");
  return location ? new URL(location).pathname : null;
}

beforeEach(() => {
  vi.stubEnv("API_BASE_URL_INTERNAL", "http://gaia-backend:8000/api/v1/");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("/ on a self-hosted instance", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
  });

  it("goes to the setup wizard while setup is needed", async () => {
    stubSetupStatus({ needs_setup: true, has_admin_account: false });

    expect(await homeTarget()).toBe("/setup");
  });

  it("does not trap a signed-in visitor once an admin exists", async () => {
    stubSetupStatus({ needs_setup: true });

    expect(await homeTarget("wos_session=abc")).toBe("/c");
  });

  it("goes to the app with a local-auth session", async () => {
    stubSetupStatus();

    expect(await homeTarget("gaia_session=abc")).toBe("/c");
  });

  it("goes to login when signed out", async () => {
    stubSetupStatus();

    expect(await homeTarget()).toBe("/login");
  });

  it("goes to the app when signed in", async () => {
    stubSetupStatus();

    expect(await homeTarget("wos_session=abc")).toBe("/c");
  });
});

describe("/ on hosted GAIA", () => {
  it("renders the landing page without asking the API anything", async () => {
    const fetchMock = stubSetupStatus();

    expect(await homeTarget("wos_session=abc")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("the auth mode server-rendered auth pages use", () => {
  it("is the API's, whatever a stale AUTH_MODE in the web env says", async () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
    vi.stubEnv("AUTH_MODE", "local");
    stubSetupStatus({ auth_mode: "workos" });

    expect(await resolveInstanceAuthMode()).toBe("workos");
  });
});
