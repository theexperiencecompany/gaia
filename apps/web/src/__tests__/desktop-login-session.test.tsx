// @vitest-environment jsdom
/** The Electron splash waits for a ready signal; the login page must send it when no session exists. */

import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const signalReady = vi.fn();
const fetchUserInfo = vi.fn();
const redirect = vi.fn();

vi.mock("next/navigation", () => ({
  RedirectType: { replace: "replace" },
  redirect: (...args: unknown[]) => redirect(...args),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("next/image", () => ({ default: () => null }));
vi.mock("@/hooks/useElectron", () => ({
  useElectron: () => ({
    isElectron: true,
    openExternal: vi.fn(),
    signalReady,
  }),
}));
vi.mock("@/features/auth/api/authApi", () => ({
  authApi: { fetchUserInfo: () => fetchUserInfo() },
}));

import { DesktopLoginClient } from "@/app/[locale]/(landing)/desktop-login/desktop-login-client";

describe("DesktopLoginClient", () => {
  it("dismisses the splash when the stored session is gone", async () => {
    fetchUserInfo.mockRejectedValueOnce(new Error("401"));

    render(<DesktopLoginClient isSelfHosted />);

    await waitFor(() => expect(signalReady).toHaveBeenCalledOnce());
    expect(redirect).not.toHaveBeenCalled();
  });

  it("hands a valid session straight to the app", async () => {
    fetchUserInfo.mockResolvedValueOnce({});

    render(<DesktopLoginClient isSelfHosted={false} />);

    await waitFor(() => expect(redirect).toHaveBeenCalledWith("/c", "replace"));
  });

  it("keeps the hosted page's black backdrop and card shape", () => {
    fetchUserInfo.mockReturnValueOnce(new Promise(() => undefined));

    const { container, getByRole } = render(
      <DesktopLoginClient isSelfHosted={false} />,
    );

    expect(container.firstElementChild?.className).toContain("bg-black");
    const heading = getByRole("heading", { name: "Welcome to GAIA Desktop" });
    expect(heading.closest(".rounded-4xl")).not.toBeNull();
  });
});
