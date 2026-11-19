// @vitest-environment jsdom
import { EMAIL_CHANNEL_DESCRIPTION } from "@gaia/shared";
import type { ChannelPreferences } from "@gaia/shared/types";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  linkedPlatform,
  platformLinks,
} from "@/__tests__/helpers/platformLinks";
import { renderWithQueryClient } from "@/__tests__/helpers/queryClient";
import NotificationSettings from "@/features/settings/components/NotificationSettings";
import { toast } from "@/lib/toast";

/**
 * Regression: a failed channel-preferences read used to be swallowed, leaving
 * the all-true initializer on screen. A user whose stored `email` preference was
 * `false` saw Email enabled, and toggling from that reading wrote the wrong
 * value back. The page now waits behind an error + retry until the stored
 * preferences actually load.
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}));

const { getChannels, putChannels, getLinks, fetchPriority, updatePriority } =
  vi.hoisted(() => ({
    getChannels: vi.fn(),
    putChannels: vi.fn(),
    getLinks: vi.fn(),
    fetchPriority: vi.fn(),
    updatePriority: vi.fn(),
  }));
const READS: Record<string, () => unknown> = {
  "/api/v1/notifications/preferences/channels": () => getChannels(),
  "/api/v1/platform-links": () => getLinks(),
  "/api/v1/user/chat-channel-priority": () => fetchPriority(),
};
vi.mock("@/lib/api/typed", () => ({
  api: {
    get: (path: string) => READS[path](),
    patch: (_path: string, init: { body: { priority: string[] } }) =>
      updatePriority(init.body.priority),
    put: (_path: string, init: { body: Partial<ChannelPreferences> }) =>
      putChannels(init.body),
    post: vi.fn(),
    delete: vi.fn(),
  },
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

function mockLinked(...platforms: string[]) {
  getLinks.mockResolvedValue(platformLinks(...platforms));
}

function render(ui: ReactElement) {
  return renderWithQueryClient(ui);
}

async function findChannels() {
  return within(await screen.findByRole("region", { name: "Channels" }));
}

describe("NotificationSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLinked("telegram");
    getChannels.mockResolvedValue(ALL_ON);
    fetchPriority.mockResolvedValue({ priority: [] });
    updatePriority.mockImplementation((priority: string[]) =>
      Promise.resolve({ priority }),
    );
  });

  it("shows a retry instead of default preferences when the load fails", async () => {
    getChannels.mockRejectedValue(new Error("boom"));

    render(<NotificationSettings />);

    expect(
      await screen.findByRole("button", { name: "Try again" }),
    ).toBeTruthy();
    // No switch may be rendered: an all-true default would show a stored
    // `email: false` as enabled.
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("shows a retry instead of channels when the linked accounts fail to load", async () => {
    getLinks.mockRejectedValue(new Error("boom"));

    render(<NotificationSettings />);

    expect(
      await screen.findByRole("button", { name: "Try again" }),
    ).toBeTruthy();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(
      screen.queryByRole("link", { name: "Manage linked accounts" }),
    ).toBeNull();
  });

  it("shows a retry instead of a guessed first channel when the stored order fails to load", async () => {
    mockLinked("telegram", "whatsapp");
    fetchPriority.mockRejectedValue(new Error("boom"));

    render(<NotificationSettings />);

    expect(
      await screen.findByRole("button", { name: "Try again" }),
    ).toBeTruthy();
    expect(screen.queryByText("Text me first on")).toBeNull();
  });

  it("renders the stored preferences after a successful retry", async () => {
    getChannels
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

  it("flips a channel at once and puts it back, naming the channel, when the save fails", async () => {
    putChannels.mockRejectedValue(new Error("boom"));

    render(<NotificationSettings />);
    const emailSwitch = (await screen.findByRole("switch", {
      name: "Enable Email notifications",
    })) as HTMLInputElement;
    fireEvent.click(emailSwitch);

    await waitFor(() =>
      expect(putChannels).toHaveBeenCalledWith({ email: false }),
    );
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Couldn't update Email notifications",
      ),
    );
    expect(emailSwitch.checked).toBe(true);
  });

  it("says the email switch controls GAIA's emails, not notification delivery", async () => {
    render(<NotificationSettings />);

    expect(await screen.findByText(EMAIL_CHANNEL_DESCRIPTION)).toBeTruthy();
  });

  it("shows each chat app's link status and groups the rest into one row to Linked Accounts", async () => {
    render(<NotificationSettings />);

    const channels = await findChannels();
    await channels.findByRole("switch", {
      name: "Enable Telegram notifications",
    });
    expect(channels.getByText("Connected")).toBeTruthy();
    expect(channels.getAllByRole("switch")).toHaveLength(2);
    expect(
      channels.getByText("WhatsApp, iMessage, Slack, Discord"),
    ).toBeTruthy();
    expect(
      channels
        .getByRole("link", { name: "Manage linked accounts" })
        .getAttribute("href"),
    ).toBe("/settings/linked-accounts");
    expect(channels.queryByRole("button", { name: /^Connect/ })).toBeNull();
    expect(channels.queryByRole("button", { name: /^More for/ })).toBeNull();
    expect(channels.queryByRole("button", { name: "Open chat" })).toBeNull();
  });

  it("names the linked account on its row", async () => {
    getLinks.mockResolvedValue(
      platformLinks(linkedPlatform("telegram", { username: "aryan" })),
    );

    render(<NotificationSettings />);

    expect(
      await (await findChannels()).findByText("Connected as @aryan"),
    ).toBeTruthy();
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
