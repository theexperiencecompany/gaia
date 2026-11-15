// @vitest-environment jsdom
import { EMAIL_CHANNEL_DESCRIPTION } from "@gaia/shared";
import type { ChannelPreferences } from "@gaia/shared/types";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NotificationSettings from "@/features/settings/components/NotificationSettings";
import { api } from "@/lib/api/typed";
import { NotificationsAPI } from "@/services/api/notifications";

/**
 * Regression: a failed `getChannelPreferences()` used to be swallowed, leaving
 * the all-true initializer on screen. A user whose stored `email` preference was
 * `false` saw Email enabled — and toggling from that reading wrote the wrong
 * value back. The page now waits behind an error + retry until the stored
 * preferences actually load.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}));

vi.mock("@/lib/api/typed", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

vi.mock("@/services/api/notifications", () => ({
  NotificationsAPI: {
    getChannelPreferences: vi.fn(),
    updateChannelPreference: vi.fn(),
  },
}));

const { fetchPriority, updatePriority } = vi.hoisted(() => ({
  fetchPriority: vi.fn(),
  updatePriority: vi.fn(),
}));
vi.mock("@/features/settings/api/chatChannelApi", () => ({
  chatChannelApi: { fetchPriority, updatePriority },
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

vi.mock("@/features/settings/components/QuietHoursSettings", () => ({
  QuietHoursSettings: () => null,
}));

const ALL_ON: ChannelPreferences = {
  telegram: true,
  discord: true,
  whatsapp: true,
  slack: true,
  imessage: true,
  email: true,
};

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

async function findChannels() {
  return within(await screen.findByRole("region", { name: "Channels" }));
}

describe("NotificationSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLinked("telegram");
    vi.mocked(NotificationsAPI.getChannelPreferences).mockResolvedValue(ALL_ON);
    fetchPriority.mockResolvedValue({ priority: [] });
    updatePriority.mockImplementation((priority: string[]) =>
      Promise.resolve({ priority }),
    );
  });

  it("shows a retry instead of default preferences when the load fails", async () => {
    vi.mocked(NotificationsAPI.getChannelPreferences).mockRejectedValue(
      new Error("boom"),
    );

    render(<NotificationSettings />);

    expect(
      await screen.findByRole("button", { name: "Try again" }),
    ).toBeTruthy();
    // No switch may be rendered: an all-true default would show a stored
    // `email: false` as enabled.
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("shows a retry instead of channels when the linked accounts fail to load", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("boom"));

    render(<NotificationSettings />);

    expect(
      await screen.findByRole("button", { name: "Try again" }),
    ).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Connect/ })).toBeNull();
  });

  it("renders the stored preferences after a successful retry", async () => {
    vi.mocked(NotificationsAPI.getChannelPreferences)
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({ ...ALL_ON, email: false });

    render(<NotificationSettings />);
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    const emailSwitch = (await screen.findByRole("switch", {
      name: "Enable Email notifications",
    })) as HTMLInputElement;
    const telegramSwitch = (await screen.findByRole("switch", {
      name: "Enable Telegram notifications",
    })) as HTMLInputElement;

    await waitFor(() => expect(emailSwitch.checked).toBe(false));
    expect(telegramSwitch.checked).toBe(true);
  });

  it("says the email switch controls GAIA's emails, not notification delivery", async () => {
    render(<NotificationSettings />);

    expect(await screen.findByText(EMAIL_CHANNEL_DESCRIPTION)).toBeTruthy();
  });

  it("lists every chat app in one section: switches for linked, an inline Connect for the rest", async () => {
    render(<NotificationSettings />);

    const channels = await findChannels();
    await channels.findByRole("switch", {
      name: "Enable Telegram notifications",
    });
    expect(channels.getByText("Connected")).toBeTruthy();
    expect(channels.getAllByRole("switch")).toHaveLength(2);
    for (const label of ["WhatsApp", "iMessage", "Slack", "Discord"]) {
      expect(
        channels.getByRole("button", { name: `Connect ${label}` }),
      ).toBeTruthy();
    }
    expect(
      channels.getByText("Bring GAIA into your Slack workspace"),
    ).toBeTruthy();
    expect(screen.getAllByRole("region")).toHaveLength(1);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText(/Linked Accounts/)).toBeNull();
  });

  it("says how to reach GAIA on a linked app that has no chat to open", async () => {
    mockLinked("slack");

    render(<NotificationSettings />);

    expect(
      await (await findChannels()).findByText(
        "Connected · Use /gaia in Slack to chat with GAIA",
      ),
    ).toBeTruthy();
  });

  it("disconnects a linked platform from its row and offers Connect again", async () => {
    vi.mocked(api.delete).mockResolvedValue({});

    render(<NotificationSettings />);
    const channels = await findChannels();
    await channels.findByRole("switch", {
      name: "Enable Telegram notifications",
    });

    mockLinked();
    fireEvent.click(
      channels.getByRole("button", { name: "More for Telegram" }),
    );
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
      await channels.findByRole("button", { name: "Connect Telegram" }),
    ).toBeTruthy();
    expect(
      channels.queryByRole("switch", { name: "Enable Telegram notifications" }),
    ).toBeNull();
  });

  it("names the linked account on its row", async () => {
    vi.mocked(api.get).mockResolvedValue({
      platform_links: {
        telegram: { ...link("telegram"), username: "aryan" },
      },
    });

    render(<NotificationSettings />);

    expect(
      await (await findChannels()).findByText("Connected as @aryan"),
    ).toBeTruthy();
  });

  it("connects an unlinked platform in place and turns its row into a switch", async () => {
    vi.mocked(api.post).mockResolvedValue({
      auth_url: "https://slack.example/oauth",
    });
    const popup = { closed: false };
    vi.spyOn(window, "open").mockReturnValue(popup as Window);

    render(<NotificationSettings />);
    const channels = await findChannels();
    const connect = await channels.findByRole("button", {
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
      await channels.findByRole(
        "switch",
        { name: "Enable Slack notifications" },
        { timeout: 2000 },
      ),
    ).toBeTruthy();
    expect(
      channels.queryByRole("button", { name: "Connect Slack" }),
    ).toBeNull();
  });

  it("offers no first-channel choice with fewer than two linked platforms", async () => {
    render(<NotificationSettings />);

    await (await findChannels()).findByRole("switch", {
      name: "Enable Telegram notifications",
    });
    expect(screen.queryByText("Text me first on")).toBeNull();
  });

  it("puts the chosen platform first and keeps the rest of the order", async () => {
    mockLinked("telegram", "whatsapp", "slack");
    fetchPriority.mockResolvedValue({
      priority: ["discord", "telegram", "whatsapp", "slack"],
    });

    render(<NotificationSettings />);
    const channels = await findChannels();
    expect(await channels.findByText("Text me first on")).toBeTruthy();
    const trigger = channels.getByRole("button", { name: /Text me first on/ });
    await waitFor(() => expect(trigger.textContent).toContain("Telegram"));

    fireEvent.click(trigger);
    fireEvent.click(await screen.findByRole("option", { name: "Slack" }));

    await waitFor(() =>
      expect(updatePriority).toHaveBeenCalledWith([
        "slack",
        "telegram",
        "whatsapp",
        "discord",
      ]),
    );
    await waitFor(() => expect(trigger.textContent).toContain("Slack"));
  });
});
