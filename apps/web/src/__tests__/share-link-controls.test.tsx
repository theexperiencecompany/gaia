// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createShortLink: vi.fn(),
  fetchShareState: vi.fn(),
  stopSharingShortLink: vi.fn(),
}));
const toastSuccess = vi.hoisted(() => vi.fn());
const copyShortLink = vi.hoisted(() => vi.fn());

vi.mock("@/features/short-links/api/shortLinksApi", () => api);
vi.mock("@/features/short-links/utils/copyShortLink", () => ({
  copyShortLink,
}));
vi.mock("@/lib/toast", () => ({ toast: { success: toastSuccess } }));

import { ShareLinkControls } from "@/features/short-links/components/ShareLinkControls";

const LIVE_URL = "https://heygaia.link/abcdefghijk";

function renderControls() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ShareLinkControls targetType="briefing" targetId="b1" />
    </QueryClientProvider>,
  );
}

async function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: "Share" }));
  await screen.findByRole("menuitem", { name: /Copy link/ });
}

describe("ShareLinkControls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("is one labelled Share control, not bare icons", () => {
    api.fetchShareState.mockResolvedValue(null);
    renderControls();

    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Share" }).textContent).toBe(
      "Share",
    );
  });

  it("never offers Stop sharing for something that was never shared", async () => {
    api.fetchShareState.mockResolvedValue(null);
    renderControls();

    await openMenu();
    await waitFor(() =>
      expect(api.fetchShareState).toHaveBeenCalledWith("briefing", "b1"),
    );

    expect(screen.queryByRole("menuitem", { name: /Stop sharing/ })).toBeNull();
  });

  it("offers Stop sharing once a live link exists and confirms the revoke", async () => {
    api.fetchShareState.mockResolvedValue(LIVE_URL);
    api.stopSharingShortLink.mockResolvedValue(true);
    renderControls();

    await openMenu();
    fireEvent.click(
      await screen.findByRole("menuitem", { name: /Stop sharing/ }),
    );

    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(
        "Sharing stopped",
        expect.anything(),
      ),
    );
  });

  it("says nothing when the link was already gone", async () => {
    api.fetchShareState.mockResolvedValue(LIVE_URL);
    api.stopSharingShortLink.mockResolvedValue(false);
    renderControls();

    await openMenu();
    fireEvent.click(
      await screen.findByRole("menuitem", { name: /Stop sharing/ }),
    );

    await waitFor(() => expect(api.stopSharingShortLink).toHaveBeenCalled());
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it("copies the live link without minting a new one", async () => {
    api.fetchShareState.mockResolvedValue(LIVE_URL);
    renderControls();

    await openMenu();
    await screen.findByRole("menuitem", { name: /Stop sharing/ });
    fireEvent.click(screen.getByRole("menuitem", { name: /Copy link/ }));

    await waitFor(() => expect(copyShortLink).toHaveBeenCalledWith(LIVE_URL));
    expect(api.createShortLink).not.toHaveBeenCalled();
  });
});
