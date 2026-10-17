// @vitest-environment jsdom
/** Skipping the AI provider step records the dismissal, so the wizard stops reopening on every visit. */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { dismissSetupWizard } = vi.hoisted(() => ({
  dismissSetupWizard: vi.fn(async () => ({ wizard_dismissed: true })),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/features/auth/hooks/useLoginModal", () => ({
  useLoginModalActions: () => ({
    suppressModal: vi.fn(),
    unsuppressModal: vi.fn(),
  }),
}));
vi.mock("@/features/settings/api/providersApi", () => ({
  providersApi: { dismissSetupWizard },
}));
vi.mock("@/features/settings/hooks/useProviderCatalog", () => ({
  useProviderCatalog: () => ({
    data: { providers: {}, custom_presets: {}, llm_provider_keys: ["openai"] },
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
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/features/setup-wizard/components/steps/ProviderStep", () => ({
  ProviderStep: () => <div>provider form</div>,
}));
vi.mock("@/features/setup-wizard/components/steps/SearchStep", () => ({
  SearchStep: () => <div>search form</div>,
}));

import { SetupWizard } from "@/features/setup-wizard/components/SetupWizard";

describe("SetupWizard provider step", () => {
  it("records the dismissal when the admin skips it with no provider", async () => {
    render(<SetupWizard />);
    expect(screen.getByText("provider form")).toBeTruthy();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /skip for now/i }));
    });

    expect(dismissSetupWizard).toHaveBeenCalledOnce();
    expect(await screen.findByText("search form")).toBeTruthy();
  });

  it("announces why Continue did not advance", () => {
    render(<SetupWizard />);

    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    expect(screen.getByRole("status").textContent).toContain(
      "Chat requires a provider",
    );
  });
});
