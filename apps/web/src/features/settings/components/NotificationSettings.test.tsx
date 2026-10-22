// @vitest-environment jsdom
import { EMAIL_CHANNEL_DESCRIPTION } from "@gaia/shared";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

vi.mock("@/lib/api/typed", () => ({
  api: { get: vi.fn() },
}));

vi.mock("@/services/api/notifications", () => ({
  NotificationsAPI: {
    getChannelPreferences: vi.fn(),
    updateChannelPreference: vi.fn(),
  },
}));

vi.mock("@/features/settings/components/ChatChannelSettings", () => ({
  ChatChannelSettings: () => null,
}));

vi.mock("@/features/settings/components/BriefingScheduleSettings", () => ({
  BriefingScheduleSettings: () => null,
}));

vi.mock("@/features/settings/components/QuietHoursSettings", () => ({
  QuietHoursSettings: () => null,
}));

function renderSettings() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <NotificationSettings />
    </QueryClientProvider>,
  );
}

describe("NotificationSettings", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.get).mockResolvedValue({
      platform_links: { telegram: { platformUserId: "tg-1" } },
    });
    vi.mocked(NotificationsAPI.getChannelPreferences).mockReset();
  });

  it("shows a retry instead of default preferences when the load fails", async () => {
    vi.mocked(NotificationsAPI.getChannelPreferences).mockRejectedValue(
      new Error("boom"),
    );

    renderSettings();

    expect(
      await screen.findByRole("button", { name: "Try again" }),
    ).toBeTruthy();
    // No switch may be rendered: an all-true default would show a stored
    // `email: false` as enabled.
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("renders the stored preferences after a successful retry", async () => {
    vi.mocked(NotificationsAPI.getChannelPreferences)
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({
        telegram: true,
        whatsapp: true,
        imessage: true,
        slack: true,
        discord: true,
        email: false,
      });

    renderSettings();
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
    vi.mocked(NotificationsAPI.getChannelPreferences).mockResolvedValue({
      telegram: true,
      discord: true,
      whatsapp: true,
      slack: true,
      imessage: true,
      email: true,
    });

    renderSettings();

    expect(await screen.findByText(EMAIL_CHANNEL_DESCRIPTION)).toBeTruthy();
  });
});
