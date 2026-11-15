// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LinkedAccountsSettings from "@/features/settings/components/LinkedAccountsSettings";
import { api } from "@/lib/api/typed";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}));

vi.mock("@/lib/api/typed", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid: true, isUnknown: false }),
}));

vi.mock("@/features/settings/hooks/useSetupStatus", () => ({
  useDeployment: () => ({ bills: true }),
}));

vi.mock("@/stores/upgradeModalStore", () => ({
  useUpgradeModalStore: (selector: (s: unknown) => unknown) =>
    selector({ openModal: vi.fn() }),
}));

function link(platform: string) {
  return {
    platform,
    platformUserId: `${platform}-1`,
    username: null,
    displayName: null,
    connectedAt: null,
  };
}

function mockLinked(...platforms: string[]) {
  vi.mocked(api.get).mockResolvedValue({
    platform_links: Object.fromEntries(platforms.map((p) => [p, link(p)])),
  });
}

describe("LinkedAccountsSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLinked("telegram");
  });

  it("names the linked account on its row", async () => {
    vi.mocked(api.get).mockResolvedValue({
      platform_links: {
        telegram: { ...link("telegram"), username: "aryan" },
      },
    });

    render(<LinkedAccountsSettings />);

    expect(await screen.findByText("Connected as @aryan")).toBeTruthy();
  });

  it("says how to reach GAIA on a linked app that has no chat to open", async () => {
    mockLinked("slack");

    render(<LinkedAccountsSettings />);

    expect(
      await screen.findByText(
        "Connected · Use /gaia in Slack to chat with GAIA",
      ),
    ).toBeTruthy();
  });

  it("disconnects a linked platform from its menu and offers Connect again", async () => {
    vi.mocked(api.delete).mockResolvedValue({});

    render(<LinkedAccountsSettings />);
    const menu = await screen.findByRole("button", {
      name: "More for Telegram",
    });
    await waitFor(() =>
      expect((menu as HTMLButtonElement).disabled).toBe(false),
    );

    mockLinked();
    fireEvent.click(menu);
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Disconnect" }),
    );

    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(
        "/api/v1/platform-links/{platform}",
        expect.objectContaining({ path: { platform: "telegram" } }),
      ),
    );
    expect(
      await screen.findByRole("button", { name: "Connect Telegram" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "More for Telegram" }),
    ).toBeNull();
  });

  it("connects an unlinked platform in place and turns its row into a linked one", async () => {
    vi.mocked(api.post).mockResolvedValue({
      auth_url: "https://slack.example/oauth",
    });
    const popup = { closed: false };
    vi.spyOn(window, "open").mockReturnValue(popup as Window);

    render(<LinkedAccountsSettings />);
    const connect = await screen.findByRole("button", {
      name: "Connect Slack",
    });
    await waitFor(() =>
      expect((connect as HTMLButtonElement).disabled).toBe(false),
    );

    fireEvent.click(connect);

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/platform-links/{platform}/connect",
        { path: { platform: "slack" }, body: {}, silent: true },
      ),
    );
    expect(window.open).toHaveBeenCalledWith(
      "https://slack.example/oauth",
      "Connect slack",
      expect.any(String),
    );

    mockLinked("telegram", "slack");
    popup.closed = true;

    expect(
      await screen.findByRole(
        "button",
        { name: "More for Slack" },
        { timeout: 2000 },
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Connect Slack" })).toBeNull();
  });
});
