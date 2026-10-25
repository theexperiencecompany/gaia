// @vitest-environment jsdom
/** A self-hosted instance's Bots page offers its own bots, never GAIA Cloud's. */

import type { InstanceBots, SetupStatusResponse } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchSetupStatus = vi.fn<() => Promise<SetupStatusResponse>>();

vi.mock("@/features/settings/api/providersApi", async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import("@/features/settings/api/providersApi")
    >();
  return {
    ...actual,
    providersApi: { fetchSetupStatus: () => fetchSetupStatus() },
  };
});

import BotsPage from "@/features/bots/components/BotsPage";

const NO_BOTS: InstanceBots = {
  telegram_username: null,
  discord_client_id: null,
  slack_workspace_url: null,
};

const status = (bots: InstanceBots): SetupStatusResponse => ({
  auth_mode: "local",
  deployment: {
    kind: "selfhost",
    bills: false,
    local_code_sandbox: false,
    blob_store: "local",
    gaia_support: false,
    instance_toolkits: true,
    private_network_endpoints: true,
  },
  has_admin_account: true,
  registration_policy: "invite_only",
  needs_setup: false,
  wizard_dismissed: false,
  plans_seeded: true,
  providers: {},
  features: {},
  bots,
});

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BotsPage />
    </QueryClientProvider>,
  );
}

function hrefs(): string[] {
  return Array.from(document.querySelectorAll("a")).map(
    (a) => a.getAttribute("href") ?? "",
  );
}

describe("BotsPage", () => {
  it("links to the instance's own bots and names the command for the rest", async () => {
    fetchSetupStatus.mockResolvedValue(
      status({
        ...NO_BOTS,
        telegram_username: "my_gaia_bot",
        slack_workspace_url: "https://acme.slack.com/",
      }),
    );

    renderPage();

    await waitFor(() => expect(hrefs()).toContain("https://t.me/my_gaia_bot"));
    expect(hrefs()).toContain("https://acme.slack.com/");
    expect(screen.getByText("gaia bots add discord")).toBeTruthy();
    expect(screen.queryByText("gaia bots add telegram")).toBeNull();
    expect(hrefs().some((href) => href.includes("heygaia_bot"))).toBe(false);
    expect(screen.queryByText("WhatsApp")).toBeNull();
  });

  it("invites the instance's Discord app, not GAIA Cloud's", async () => {
    fetchSetupStatus.mockResolvedValue(
      status({ ...NO_BOTS, discord_client_id: "4242" }),
    );

    renderPage();

    await waitFor(() =>
      expect(
        hrefs().some((href) =>
          href.startsWith(
            "https://discord.com/oauth2/authorize?client_id=4242",
          ),
        ),
      ).toBe(true),
    );
  });

  it("keeps GAIA Cloud's bots on hosted GAIA without asking for setup status", () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "");

    renderPage();

    expect(hrefs()).toContain("https://t.me/heygaia_bot");
    expect(screen.getByText("WhatsApp")).toBeTruthy();
    expect(fetchSetupStatus).not.toHaveBeenCalled();
  });
});
