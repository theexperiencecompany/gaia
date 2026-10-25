// @vitest-environment jsdom
/** On a local-auth self-host instance, Sign in goes to the instance's own /login, never WorkOS. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
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

function withQueryClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

async function openModal(): Promise<void> {
  render(<LoginModal />, { wrapper: withQueryClient() });
  await act(async () => {
    await Promise.resolve();
  });
}

async function pressSignIn(): Promise<void> {
  await openModal();
  fireEvent.click(await screen.findByRole("button", { name: /sign in/i }));
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

  it("offers a retry, never WorkOS, when the instance status cannot be read", async () => {
    fetchSetupStatus.mockRejectedValueOnce(
      new Error("503 Service Unavailable"),
    );

    await openModal();
    const retry = await screen.findByRole("button", { name: /try again/i });

    expect(screen.queryByRole("button", { name: /sign in/i })).toBeNull();
    expect(handleAuthLogin).not.toHaveBeenCalled();

    fetchSetupStatus.mockResolvedValue({ auth_mode: "local" });
    fireEvent.click(retry);
    fireEvent.click(await screen.findByRole("button", { name: /sign in/i }));

    expect(push).toHaveBeenCalledWith("/login");
    expect(handleAuthLogin).not.toHaveBeenCalled();
  });
});
