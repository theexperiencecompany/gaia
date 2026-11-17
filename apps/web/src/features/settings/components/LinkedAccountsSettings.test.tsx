// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  linkedPlatform,
  platformLinks,
} from "@/__tests__/helpers/platformLinks";
import { renderWithQueryClient } from "@/__tests__/helpers/queryClient";
import LinkedAccountsSettings from "@/features/settings/components/LinkedAccountsSettings";
import { api } from "@/lib/api/typed";
import { toast } from "@/lib/toast";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}));

vi.mock("@/lib/analytics", () => ({
  track: vi.fn(),
}));

vi.mock("@/lib/api/typed", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const plan = { isPaid: true, isUnknown: false, bills: true };
vi.mock("@/features/pricing/hooks/useIsPaid", () => ({
  useIsPaid: () => ({ isPaid: plan.isPaid, isUnknown: plan.isUnknown }),
}));

vi.mock("@/features/settings/hooks/useSetupStatus", () => ({
  useDeployment: () => ({ bills: plan.bills }),
}));

const openUpgradeModal = vi.fn();
vi.mock("@/stores/upgradeModalStore", () => ({
  useUpgradeModalStore: (selector: (s: unknown) => unknown) =>
    selector({ openModal: openUpgradeModal }),
}));

function mockLinked(...platforms: string[]) {
  vi.mocked(api.get).mockResolvedValue(platformLinks(...platforms));
}

function render() {
  return renderWithQueryClient(<LinkedAccountsSettings />);
}

/** The platform's row, found through its own Connect or menu button once the links load. */
async function findPlatformRow(label: string) {
  const name = new RegExp(`^(Connect|More for) ${label}$`);
  const action = await waitFor(() => {
    const button = screen.getByRole("button", { name }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    return button;
  });
  const row = action.closest("div.flex.px-4") as HTMLElement;
  expect(row).not.toBeNull();
  return within(row);
}

describe("LinkedAccountsSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(plan, { isPaid: true, isUnknown: false, bills: true });
    mockLinked("telegram");
  });

  it("offers a retry instead of a Connect for every platform when the links fail to load", async () => {
    vi.mocked(api.get)
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValue(platformLinks("telegram"));

    render();

    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(screen.queryByRole("button", { name: /^Connect / })).toBeNull();
    expect(
      await screen.findByRole("button", { name: "More for Telegram" }),
    ).toBeTruthy();
  });

  it("names the linked account on its row", async () => {
    vi.mocked(api.get).mockResolvedValue(
      platformLinks(linkedPlatform("telegram", { username: "aryan" })),
    );

    render();

    expect(await screen.findByText("Connected as @aryan")).toBeTruthy();
  });

  it("says how to reach GAIA on a linked app that has no chat to open", async () => {
    mockLinked("slack");

    render();

    expect(
      await screen.findByText(
        "Connected · Use /gaia in Slack to chat with GAIA",
      ),
    ).toBeTruthy();
  });

  it("disconnects a linked platform from its menu, names it, and offers Connect again", async () => {
    mockLinked("imessage");
    vi.mocked(api.delete).mockResolvedValue({});

    render();
    const row = await findPlatformRow("iMessage");

    mockLinked();
    fireEvent.click(row.getByRole("button", { name: "More for iMessage" }));
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Disconnect" }),
    );

    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith(
        "/api/v1/platform-links/{platform}",
        expect.objectContaining({ path: { platform: "imessage" } }),
      ),
    );
    expect(
      await screen.findByRole("button", { name: "Connect iMessage" }),
    ).toBeTruthy();
    expect(toast.success).toHaveBeenCalledWith("Disconnected from iMessage");
  });

  it("names the platform and says why when disconnecting fails", async () => {
    vi.mocked(api.delete).mockRejectedValue(
      new Error("That account is still linked to a workflow."),
    );

    render();
    const row = await findPlatformRow("Telegram");
    fireEvent.click(row.getByRole("button", { name: "More for Telegram" }));
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Disconnect" }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Couldn't disconnect Telegram", {
        description: "That account is still linked to a workflow.",
      }),
    );
    expect(row.getByRole("button", { name: "More for Telegram" })).toBeTruthy();
  });

  it("connects an unlinked platform in place and turns its row into a linked one", async () => {
    vi.mocked(api.post).mockResolvedValue({
      auth_url: "https://slack.example/oauth",
    });
    const popup = { closed: false };
    vi.spyOn(window, "open").mockReturnValue(popup as Window);

    render();
    const row = await findPlatformRow("Slack");

    fireEvent.click(row.getByRole("button", { name: "Connect Slack" }));

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

  describe("open chat", () => {
    it.each([
      ["telegram", "Telegram"],
      ["whatsapp", "WhatsApp"],
      ["imessage", "iMessage"],
    ])(
      "opens the %s conversation and navigates to it",
      async (platform, label) => {
        mockLinked(platform);
        vi.mocked(api.post).mockResolvedValue({
          conversation_id: `conv-${platform}`,
        });

        render();
        const row = await findPlatformRow(label);
        fireEvent.click(row.getByRole("button", { name: "Open chat" }));

        await waitFor(() =>
          expect(api.post).toHaveBeenCalledWith(
            "/api/v1/platform-links/{platform}/conversation",
            { path: { platform } },
          ),
        );
        await waitFor(() =>
          expect(push).toHaveBeenCalledWith(`/c/conv-${platform}`),
        );
      },
    );

    it("does not offer a chat for other platforms or for a disconnected account", async () => {
      mockLinked("slack", "discord");

      render();

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
      expect(api.post).not.toHaveBeenCalled();
    });
  });

  // The premium gate reads useIsPaid(): a cold plan read is unknown, never "free",
  // so a paying user is never shown the badge or sent to the paywall mid-fetch.
  describe("iMessage (premium) gate", () => {
    beforeEach(() => mockLinked());

    it("never paywalls a free user on an instance that does not bill", async () => {
      Object.assign(plan, { isPaid: false, bills: false });
      render();
      const row = await findPlatformRow("iMessage");

      expect(row.queryByText("Pro")).toBeNull();
      fireEvent.click(row.getByRole("button", { name: "Connect iMessage" }));
      expect(openUpgradeModal).not.toHaveBeenCalled();
    });

    it("shows the Pro badge and paywalls the connect attempt for a known-free user", async () => {
      plan.isPaid = false;
      render();
      const row = await findPlatformRow("iMessage");

      expect(row.getByText("Pro")).not.toBeNull();
      fireEvent.click(row.getByRole("button", { name: "Connect iMessage" }));
      expect(openUpgradeModal).toHaveBeenCalledTimes(1);
    });

    it("does not show the Pro badge and does not paywall the connect attempt for a paid user", async () => {
      render();
      const row = await findPlatformRow("iMessage");

      expect(row.queryByText("Pro")).toBeNull();
      fireEvent.click(row.getByRole("button", { name: "Connect iMessage" }));
      expect(openUpgradeModal).not.toHaveBeenCalled();
    });

    it("does not show the Pro badge and lets the connect attempt proceed while the plan is still unknown", async () => {
      Object.assign(plan, { isPaid: false, isUnknown: true });
      render();
      const row = await findPlatformRow("iMessage");

      expect(row.queryByText("Pro")).toBeNull();
      fireEvent.click(row.getByRole("button", { name: "Connect iMessage" }));
      expect(openUpgradeModal).not.toHaveBeenCalled();
    });
  });
});
