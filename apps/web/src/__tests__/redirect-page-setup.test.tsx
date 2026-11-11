// @vitest-environment jsdom
/** After a self-host sign-in, only the admin with setup still owed lands in the wizard. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SetupStatus } from "@/features/settings/api/providersApi";

const { replace, fetchSetupStatus, fetchUserInfo, toastError } = vi.hoisted(
  () => ({
    replace: vi.fn(),
    fetchSetupStatus: vi.fn(),
    fetchUserInfo: vi.fn(),
    toastError: vi.fn(),
  }),
);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
}));
vi.mock("@/features/settings/api/providersApi", () => ({
  providersApi: { fetchSetupStatus },
}));
vi.mock("@/features/auth/api/authApi", () => ({
  authApi: { fetchUserInfo },
}));
vi.mock("@/lib/toast", () => ({
  toast: { error: toastError, success: vi.fn() },
}));

import RedirectPage from "@/app/[locale]/(main)/redirect/page";

const PENDING: SetupStatus = {
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
    instance_toolkits: true,
    private_network_endpoints: true,
  },
  providers: {},
  features: {},
  plans_seeded: false,
  bots: {
    telegram_username: null,
    discord_client_id: null,
    slack_workspace_url: null,
  },
};

function signedInAs(role: "admin" | "member"): void {
  fetchUserInfo.mockResolvedValue({ user_id: "u1", role });
}

async function landing(): Promise<string | undefined> {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(<RedirectPage />, { wrapper });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(200);
  });
  return replace.mock.calls.at(-1)?.[0];
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("the post-sign-in redirect on a self-hosted instance", () => {
  it("sends the admin to the wizard while no AI provider works", async () => {
    fetchSetupStatus.mockResolvedValue(PENDING);
    signedInAs("admin");

    expect(await landing()).toBe("/setup");
  });

  it("sends the admin to chat once they skipped the wizard", async () => {
    fetchSetupStatus.mockResolvedValue({ ...PENDING, wizard_dismissed: true });
    signedInAs("admin");

    expect(await landing()).toBe("/c");
  });

  it("sends a member to chat, never into the admin's wizard", async () => {
    fetchSetupStatus.mockResolvedValue(PENDING);
    signedInAs("member");

    expect(await landing()).toBe("/c");
  });

  it("says so and continues to chat when the status cannot be read", async () => {
    fetchSetupStatus.mockRejectedValue(new Error("503"));
    signedInAs("admin");

    expect(await landing()).toBe("/c");
    expect(toastError).toHaveBeenCalledOnce();
  });
});
