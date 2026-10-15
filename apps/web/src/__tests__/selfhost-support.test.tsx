// @vitest-environment jsdom
/** A self-hosted instance offers GitHub instead of a support form whose requests would reach GAIA. */

import type { SetupStatusResponse } from "@shared/api/generated";
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

import ContactForm from "@/features/contact/components/ContactForm";
import { GAIA_GITHUB_ISSUES_URL } from "@/features/support/constants/supportConstants";

const status = (gaia_support: boolean): SetupStatusResponse => ({
  auth_mode: "local",
  deployment: {
    kind: "selfhost",
    bills: false,
    local_code_sandbox: false,
    blob_store: "local",
    gaia_support: gaia_support,
    instance_toolkits: true,
    private_network_endpoints: true,
  },
  has_admin_account: true,
  registration_policy: "invite_only",
  needs_setup: false,
  wizard_dismissed: false,
  features: {},
  plans_seeded: true,
  bots: {
    telegram_username: null,
    discord_client_id: null,
    slack_workspace_url: null,
  },
  providers: {},
});

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

function renderForm() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ContactForm />
    </QueryClientProvider>,
  );
}

describe("ContactForm", () => {
  it("links to GitHub instead of the form on a self-hosted instance", async () => {
    fetchSetupStatus.mockResolvedValue(status(false));

    renderForm();

    await waitFor(() =>
      expect(
        screen.getByText("Open an issue").closest("a")?.getAttribute("href"),
      ).toBe(GAIA_GITHUB_ISSUES_URL),
    );
    expect(screen.queryByText("Submit")).toBeNull();
  });

  it("keeps the support form on hosted GAIA without asking for setup status", () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "");

    renderForm();

    expect(fetchSetupStatus).not.toHaveBeenCalled();
    expect(screen.queryByText("Open an issue")).toBeNull();
    expect(screen.getAllByText("Request Type").length).toBeGreaterThan(0);
  });
});
