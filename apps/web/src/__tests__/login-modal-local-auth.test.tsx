// @vitest-environment jsdom
/** On a local-auth self-host instance, Sign in goes to the instance's own /login, never WorkOS. */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { push, fetchSetupStatus, handleAuthLogin } = vi.hoisted(() => ({
  push: vi.fn(),
  fetchSetupStatus: vi.fn(),
  handleAuthLogin: vi.fn(),
}));

vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/c",
  useRouter: () => ({ push }),
}));
vi.mock("@/features/settings/api/providersApi", () => ({
  providersApi: { fetchSetupStatus },
}));
vi.mock("@/features/auth/hooks/handleAuthLogin", () => ({
  handleAuthLogin,
}));

import LoginModal from "@/features/auth/components/LoginModal";
import { useLoginModalStore } from "@/stores/loginModalStore";

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_GAIA_SELFHOST", "true");
  useLoginModalStore.setState({ open: true });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

async function pressSignIn(): Promise<void> {
  render(<LoginModal />);
  await act(async () => {
    await Promise.resolve();
  });
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
}

describe("LoginModal on a self-hosted instance", () => {
  it("routes Sign in to /login under local auth", async () => {
    fetchSetupStatus.mockResolvedValue({ auth_mode: "local" });

    await pressSignIn();

    expect(push).toHaveBeenCalledWith("/login");
    expect(handleAuthLogin).not.toHaveBeenCalled();
  });

  it("keeps WorkOS when the instance runs WorkOS", async () => {
    fetchSetupStatus.mockResolvedValue({ auth_mode: "workos" });

    await pressSignIn();

    expect(handleAuthLogin).toHaveBeenCalledOnce();
    expect(push).not.toHaveBeenCalled();
  });
});
