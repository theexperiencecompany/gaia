// @vitest-environment jsdom
/** A self-hosted instance's onboarding offers only the bots it runs, and skips the step when it runs none. */

import type { InstanceBots, SetupStatusResponse } from "@shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { domAnimation, LazyMotion } from "motion/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchSetupStatus = vi.fn<() => Promise<SetupStatusResponse>>();
const skip = vi.fn();

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
vi.mock("@/features/onboarding/hooks/useTypedLines", () => ({
  usePaceDone: () => true,
}));
vi.mock("@/features/onboarding/components/OnboardingBotBubbles", () => ({
  OnboardingBotBubbles: () => null,
}));
vi.mock("@/features/onboarding/components/OnboardingPlatformPreview", () => ({
  OnboardingPlatformPreview: () => null,
}));
vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ name: "Ada", email: "ada@example.com" }),
}));
vi.mock("@/features/onboarding/hooks/useConnectPlatform", () => ({
  useConnectPlatform: () => ({
    connect: vi.fn(),
    skip,
    phoneModalOpen: false,
    phoneTarget: null,
    isSubmittingPhone: false,
    submitPhone: vi.fn(),
    closePhoneModal: vi.fn(),
  }),
}));

import { Platforms } from "@/features/onboarding/components/stages/Platforms";
import { initialState } from "@/features/onboarding/state/initial";

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

function renderStage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LazyMotion features={domAnimation}>
        <Platforms
          state={initialState}
          dispatch={vi.fn()}
          onConfirmed={vi.fn()}
        />
      </LazyMotion>
    </QueryClientProvider>,
  );
}

function platformButtons(): string[] {
  return screen
    .queryAllByRole("button")
    .map((b) => b.textContent ?? "")
    .filter((text) => text !== "Skip");
}

describe("onboarding platform pick", () => {
  it("offers only the bots a self-hosted instance runs", async () => {
    fetchSetupStatus.mockResolvedValue(
      status({
        ...NO_BOTS,
        telegram_username: "my_gaia_bot",
        discord_client_id: "42",
      }),
    );

    renderStage();

    await waitFor(() =>
      expect(platformButtons()).toEqual(["Telegram", "Discord"]),
    );
    expect(skip).not.toHaveBeenCalled();
  });

  it("skips the step on a self-hosted instance that runs no bot", async () => {
    fetchSetupStatus.mockResolvedValue(status(NO_BOTS));

    renderStage();

    await waitFor(() => expect(skip).toHaveBeenCalledOnce());
    expect(platformButtons()).toEqual([]);
  });

  it("keeps GAIA Cloud's Telegram, WhatsApp and iMessage on hosted GAIA", () => {
    vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "");

    renderStage();

    expect(platformButtons()).toEqual(["Telegram", "WhatsApp", "iMessage"]);
    expect(skip).not.toHaveBeenCalled();
  });
});
