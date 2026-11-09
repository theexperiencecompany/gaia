// @vitest-environment jsdom
/** The Electron splash waits for a ready signal; the login page must send it when no session exists. */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const signalReady = vi.fn();
const fetchUserInfo = vi.fn();
const redirect = vi.fn();
const connectSelfHostServer = vi.fn();
const switchToGaiaCloud = vi.fn();
const getDesktopSettings = vi.fn();

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
vi.mock("@/lib/electron/api", () => ({
  getElectronAPI: () => ({
    connectSelfHostServer,
    switchToGaiaCloud,
    getDesktopSettings,
  }),
}));
vi.mock("@/features/auth/api/authApi", () => ({
  authApi: { fetchUserInfo: () => fetchUserInfo() },
}));

import { DesktopLoginClient } from "@/app/[locale]/(landing)/desktop-login/desktop-login-client";

function settingsWith(selfHostOrigin: string | null) {
  return { settings: { selfHostOrigin }, icons: [] };
}

beforeEach(() => {
  vi.clearAllMocks();
  getDesktopSettings.mockResolvedValue(settingsWith(null));
});

describe("DesktopLoginClient", () => {
  it("sends a signed-out self-hosted user to the server's sign-in page", async () => {
    fetchUserInfo.mockRejectedValueOnce(new Error("401"));

    render(<DesktopLoginClient isSelfHosted serverFormReason={null} />);

    await waitFor(() => expect(signalReady).toHaveBeenCalledOnce());
    await waitFor(() =>
      expect(redirect).toHaveBeenCalledWith("/login", "replace"),
    );
  });

  it("hands a valid session straight to the app", async () => {
    fetchUserInfo.mockResolvedValueOnce({});

    render(<DesktopLoginClient isSelfHosted={false} serverFormReason={null} />);

    await waitFor(() => expect(redirect).toHaveBeenCalledWith("/c", "replace"));
  });

  it("keeps the hosted page's black backdrop and card shape", () => {
    fetchUserInfo.mockReturnValueOnce(new Promise(() => undefined));

    const { container, getByRole } = render(
      <DesktopLoginClient isSelfHosted={false} serverFormReason={null} />,
    );

    expect(container.firstElementChild?.className).toContain("bg-black");
    const heading = getByRole("heading", { name: "Welcome to GAIA Desktop" });
    expect(heading.closest(".rounded-4xl")).not.toBeNull();
  });

  it("opens the server form from the tray without skipping to the app", async () => {
    fetchUserInfo.mockResolvedValue({});

    render(
      <DesktopLoginClient isSelfHosted={false} serverFormReason="choose" />,
    );

    await waitFor(() => expect(signalReady).toHaveBeenCalledOnce());
    expect(redirect).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Server address")).toBeTruthy();
  });

  it("shows why the desktop app rejected a server", async () => {
    fetchUserInfo.mockRejectedValueOnce(new Error("401"));
    connectSelfHostServer.mockResolvedValueOnce({
      ok: false,
      error: "No GAIA server answered at this address.",
    });

    render(<DesktopLoginClient isSelfHosted={false} serverFormReason={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Use my own server" }));
    fireEvent.change(screen.getByLabelText("Server address"), {
      target: { value: "gaia.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await screen.findByText("No GAIA server answered at this address.");
    expect(connectSelfHostServer).toHaveBeenCalledWith("gaia.example.com");
  });

  it("names the unreachable server and offers GAIA Cloud", async () => {
    getDesktopSettings.mockResolvedValue(
      settingsWith("https://gaia.example.com"),
    );
    fetchUserInfo.mockRejectedValueOnce(new Error("offline"));

    render(
      <DesktopLoginClient
        isSelfHosted={false}
        serverFormReason="unreachable"
      />,
    );

    await screen.findByText(/Couldn't reach https:\/\/gaia\.example\.com/);
    expect(
      screen.queryByRole("button", { name: "Open Login in Browser" }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Use GAIA Cloud" }));
    expect(switchToGaiaCloud).toHaveBeenCalledOnce();
  });
});
