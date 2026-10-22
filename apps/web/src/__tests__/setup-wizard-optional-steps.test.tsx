// @vitest-environment jsdom
/** Continue on an optional step moves on; only a required step holds the user back. */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/features/auth/hooks/useLoginModal", () => ({
  useLoginModalActions: () => ({
    suppressModal: vi.fn(),
    unsuppressModal: vi.fn(),
  }),
}));
vi.mock("@/features/settings/hooks/useProviderCatalog", () => ({
  useProviderCatalog: () => ({
    data: { providers: {}, custom_presets: {}, llm_provider_keys: [] },
    isLoading: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/features/settings/hooks/useSetupStatus", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/settings/hooks/useSetupStatus")
  >()),
  useSetupStatus: () => ({
    data: {
      auth_mode: "local",
      has_admin_account: true,
      registration_policy: "invite_only",
      needs_setup: true,
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
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/features/settings/api/providersApi", () => ({
  providersApi: {
    dismissSetupWizard: async () => ({ wizard_dismissed: true }),
  },
}));
vi.mock("@/features/setup-wizard/components/steps/FeatureStep", () => ({
  FeatureStep: ({ feature }: { feature: string }) => (
    <div>{feature === "ai_models" ? "provider step" : "search step"}</div>
  ),
}));
vi.mock("@/features/setup-wizard/components/steps/IntegrationsStep", () => ({
  IntegrationsStep: () => <div>integrations step</div>,
}));

import { SetupWizard } from "@/features/setup-wizard/components/SetupWizard";

const continueButton = () => screen.getByRole("button", { name: /continue/i });

describe("SetupWizard optional steps", () => {
  it("moves on from web search with no key entered", async () => {
    render(<SetupWizard />);
    fireEvent.click(screen.getByRole("button", { name: /skip for now/i }));
    expect(await screen.findByText("search step")).toBeTruthy();

    fireEvent.click(continueButton());

    expect(screen.getByText("integrations step")).toBeTruthy();
    expect(screen.queryByText(/add a search key/i)).toBeNull();
  });

  it("still holds the required provider step until one is added", () => {
    render(<SetupWizard />);

    fireEvent.click(continueButton());

    expect(screen.getByText("provider step")).toBeTruthy();
    expect(screen.getByText(/chat requires a provider/i)).toBeTruthy();
  });
});
