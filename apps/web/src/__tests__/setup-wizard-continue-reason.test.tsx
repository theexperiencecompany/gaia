// @vitest-environment jsdom
/** The wizard explains a locked Continue only once the user has tried it. */

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
      has_admin_account: false,
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
vi.mock("@/features/setup-wizard/components/steps/AccountStep", () => ({
  AccountStep: () => <div>admin form</div>,
}));

import { SetupWizard } from "@/features/setup-wizard/components/SetupWizard";

const ACCOUNT_REASON = "Create the admin account above to continue.";

describe("SetupWizard admin step", () => {
  it("shows no warning before the user tries to continue", () => {
    render(<SetupWizard />);

    expect(screen.getByText("admin form")).toBeTruthy();
    expect(screen.queryByText(ACCOUNT_REASON)).toBeNull();
  });

  it("explains why it stays on the step after a Continue attempt", () => {
    render(<SetupWizard />);

    fireEvent.click(screen.getByRole("button", { name: /continue/i }));

    expect(screen.getByText(ACCOUNT_REASON)).toBeTruthy();
    expect(screen.getByText("admin form")).toBeTruthy();
  });
});
