// @vitest-environment jsdom
/** Saving the first provider flips needs_setup off; the wizard must keep going. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SetupStatus } from "@/features/settings/api/providersApi";

const replace = vi.fn();
let status: SetupStatus;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
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
    data: status,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/features/setup-wizard/components/steps/ProviderStep", () => ({
  ProviderStep: () => <div>provider step</div>,
}));

import { SetupWizard } from "@/features/setup-wizard/components/SetupWizard";

const BASE_STATUS = {
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
} as SetupStatus;

describe("SetupWizard after the first provider is saved", () => {
  it("stays on the wizard instead of jumping to chat", () => {
    status = BASE_STATUS;
    const { rerender } = render(<SetupWizard />);
    expect(screen.getByText("provider step")).toBeTruthy();

    status = { ...BASE_STATUS, needs_setup: false };
    rerender(<SetupWizard />);

    expect(screen.getByText("provider step")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });
});
