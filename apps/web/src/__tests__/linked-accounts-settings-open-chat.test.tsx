// @vitest-environment jsdom
//
// A connected Telegram, WhatsApp or iMessage account can open its bot DM from the
// settings page; the server resolves (and creates) the conversation and the
// button navigates to it. Other platforms have no chat button.
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
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

vi.mock("@/lib/analytics", () => ({
  track: vi.fn(),
}));

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api/typed", () => ({
  api: { get, post, delete: vi.fn() },
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}));

import LinkedAccountsSettings from "@/features/settings/components/LinkedAccountsSettings";

const LINKED = {
  platform: "telegram",
  platformUserId: "123",
  username: null,
  displayName: null,
  connectedAt: null,
};

async function findPlatformRow(label: string) {
  const labelEl = await screen.findByText(label);
  const row = labelEl.closest("div.flex.px-4") as HTMLElement;
  expect(row).not.toBeNull();
  const scope = within(row);
  await waitFor(() => {
    const connect = scope.getByRole("button", { name: /Connect|Disconnect/ });
    expect((connect as HTMLButtonElement).disabled).toBe(false);
  });
  return scope;
}

describe("LinkedAccountsSettings — open chat", () => {
  beforeEach(() => {
    push.mockReset();
    get.mockReset();
    post.mockReset();
    get.mockResolvedValue({ platform_links: {} });
  });

  it("opens the Telegram conversation and navigates to it", async () => {
    get.mockResolvedValue({ platform_links: { telegram: LINKED } });
    post.mockResolvedValue({ conversation_id: "conv-telegram" });

    render(<LinkedAccountsSettings />);
    const row = await findPlatformRow("Telegram");

    fireEvent.click(row.getByRole("button", { name: "Open chat" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/v1/platform-links/{platform}/conversation",
        { path: { platform: "telegram" } },
      ),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/c/conv-telegram"));
  });

  it.each([
    ["whatsapp", "WhatsApp"],
    ["imessage", "iMessage"],
  ])(
    "opens the %s conversation and navigates to it",
    async (platform, label) => {
      get.mockResolvedValue({
        platform_links: { [platform]: { ...LINKED, platform } },
      });
      post.mockResolvedValue({ conversation_id: `conv-${platform}` });

      render(<LinkedAccountsSettings />);
      const row = await findPlatformRow(label);

      fireEvent.click(row.getByRole("button", { name: "Open chat" }));

      await waitFor(() =>
        expect(push).toHaveBeenCalledWith(`/c/conv-${platform}`),
      );
    },
  );

  it("does not offer a chat for other platforms or for a disconnected account", async () => {
    get.mockResolvedValue({
      platform_links: {
        slack: { ...LINKED, platform: "slack" },
        discord: { ...LINKED, platform: "discord" },
      },
    });

    render(<LinkedAccountsSettings />);

    for (const label of [
      "Telegram",
      "WhatsApp",
      "Slack",
      "Discord",
      "iMessage",
    ]) {
      const row = await findPlatformRow(label);
      expect(row.queryByRole("button", { name: "Open chat" })).toBeNull();
    }
    expect(post).not.toHaveBeenCalled();
  });
});
