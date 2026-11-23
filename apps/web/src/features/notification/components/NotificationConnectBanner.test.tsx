// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { platformLinks } from "@/__tests__/helpers/platformLinks";
import { renderWithQueryClient } from "@/__tests__/helpers/queryClient";
import { api } from "@/lib/api/typed";
import { NotificationConnectBanner } from "./NotificationConnectBanner";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/typed", () => ({
  api: { get: vi.fn() },
}));

describe("NotificationConnectBanner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("offers to connect while a chat app is still unlinked", async () => {
    vi.mocked(api.get).mockResolvedValue(platformLinks("telegram"));

    renderWithQueryClient(<NotificationConnectBanner />);

    expect(await screen.findByRole("button", { name: "Connect" })).toBeTruthy();
  });

  it("names every chat app GAIA can notify on, iMessage included", async () => {
    vi.mocked(api.get).mockResolvedValue(platformLinks());

    renderWithQueryClient(<NotificationConnectBanner variant="full" />);

    expect(
      await screen.findByText(
        "Connect Telegram, WhatsApp, iMessage, Slack, or Discord to get GAIA notifications anywhere.",
      ),
    ).toBeTruthy();
  });

  it("stays hidden when the linked accounts could not be read, rather than claiming none are linked", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("network down"));

    renderWithQueryClient(<NotificationConnectBanner />);

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
  });
});
