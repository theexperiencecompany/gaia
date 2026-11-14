// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createShortLink: vi.fn(),
  fetchShareState: vi.fn(),
  stopSharingShortLink: vi.fn(),
  updateLinkSettings: vi.fn(),
  rotateLink: vi.fn(),
}));
const copyShortLink = vi.hoisted(() => vi.fn());

vi.mock("@/features/short-links/api/shortLinksApi", () => api);
vi.mock("@/features/short-links/utils/copyShortLink", () => ({
  copyShortLink,
}));
vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { ShareLinkControls } from "@/features/short-links/components/ShareLinkControls";
import type { ShortLinkResponse } from "@/types/features/shortLinkTypes";

const LIVE: ShortLinkResponse = {
  url: "https://heygaia.link/abcdefghijk",
  slug: "abcdefghijk",
  access: "unlisted",
  grantees: [],
  expires_at: null,
  content_max_access: null,
};
const NOW = Date.UTC(2026, 10, 12, 12, 0, 0);
const DAY_MS = 24 * 60 * 60 * 1000;

async function openSettings(link: ShortLinkResponse | null) {
  api.fetchShareState.mockResolvedValue(link);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ShareLinkControls targetType="briefing" targetId="b1" />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Share" }));
  fireEvent.click(
    await screen.findByRole("menuitem", { name: /Share settings/ }),
  );
  return screen.findByRole("dialog", { name: /Share settings/ });
}

async function chooseAccess(dialog: HTMLElement, label: RegExp) {
  fireEvent.click(within(dialog).getByRole("button", { name: /Who can open/ }));
  fireEvent.click(await screen.findByRole("option", { name: label }));
}

function addEmail(dialog: HTMLElement, value: string) {
  const input = within(dialog).getByRole("textbox", { name: /People/ });
  fireEvent.change(input, { target: { value } });
  fireEvent.keyDown(input, { key: "Enter" });
}

function save(dialog: HTMLElement) {
  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
}

describe("share settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(Date, "now").mockReturnValue(NOW);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("changing access PATCHes the live link", async () => {
    api.updateLinkSettings.mockResolvedValue({ ...LIVE, access: "owner" });
    const dialog = await openSettings(LIVE);

    await chooseAccess(dialog, /Only you/);
    save(dialog);

    await waitFor(() =>
      expect(api.updateLinkSettings).toHaveBeenCalledWith(
        LIVE.slug,
        expect.objectContaining({ access: "owner", grantees: [] }),
      ),
    );
    expect(api.createShortLink).not.toHaveBeenCalled();
  });

  it("mints the link with the chosen settings when nothing is shared yet", async () => {
    api.createShortLink.mockResolvedValue({ ...LIVE, access: "owner" });
    const dialog = await openSettings(null);

    await chooseAccess(dialog, /Only you/);
    save(dialog);

    await waitFor(() =>
      expect(api.createShortLink).toHaveBeenCalledWith(
        "briefing",
        "b1",
        expect.objectContaining({ access: "owner" }),
      ),
    );
    expect(api.updateLinkSettings).not.toHaveBeenCalled();
  });

  it("specific people needs at least one valid email before it saves", async () => {
    api.updateLinkSettings.mockResolvedValue({ ...LIVE, access: "people" });
    const dialog = await openSettings(LIVE);

    await chooseAccess(dialog, /Specific people/);
    save(dialog);
    expect(
      await within(dialog).findByText(/Add at least one email/),
    ).toBeTruthy();

    addEmail(dialog, "not-an-email");
    expect(await within(dialog).findByText(/valid email address/)).toBeTruthy();
    save(dialog);
    expect(api.updateLinkSettings).not.toHaveBeenCalled();

    addEmail(dialog, "Friend@Example.com");
    save(dialog);

    await waitFor(() =>
      expect(api.updateLinkSettings).toHaveBeenCalledWith(
        LIVE.slug,
        expect.objectContaining({
          access: "people",
          grantees: ["friend@example.com"],
        }),
      ),
    );
  });

  it("an expiry preset saves as an ISO time that far from now", async () => {
    api.updateLinkSettings.mockResolvedValue(LIVE);
    const dialog = await openSettings(LIVE);

    fireEvent.click(within(dialog).getByRole("radio", { name: "7 days" }));
    save(dialog);

    await waitFor(() =>
      expect(api.updateLinkSettings).toHaveBeenCalledWith(
        LIVE.slug,
        expect.objectContaining({
          expires_at: new Date(NOW + 7 * DAY_MS).toISOString(),
        }),
      ),
    );
  });

  it("keeps an existing expiry unless another one is picked", async () => {
    const expiring = { ...LIVE, expires_at: "2026-11-20T12:00:00Z" };
    api.updateLinkSettings.mockResolvedValue(expiring);
    const dialog = await openSettings(expiring);

    save(dialog);

    await waitFor(() => expect(api.updateLinkSettings).toHaveBeenCalled());
    expect(api.updateLinkSettings.mock.calls[0][1]).not.toHaveProperty(
      "expires_at",
    );
  });

  it("getting a new link rotates it, and copying then copies the new URL", async () => {
    const rotated = {
      ...LIVE,
      slug: "zyxwvutsrqp",
      url: "https://heygaia.link/zyxwvutsrqp",
    };
    api.rotateLink.mockResolvedValue(rotated);
    const dialog = await openSettings(LIVE);

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Get a new link" }),
    );
    expect(within(dialog).getByText(/old link stops working/)).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Replace link" }),
    );

    await waitFor(() => expect(api.rotateLink).toHaveBeenCalledWith(LIVE.slug));
    await within(dialog).findByDisplayValue(rotated.url);
    fireEvent.click(within(dialog).getByRole("button", { name: "Copy link" }));
    expect(copyShortLink).toHaveBeenCalledWith(rotated);
  });

  it("warns when the chosen access is wider than the file can be shown at", async () => {
    const dialog = await openSettings({
      ...LIVE,
      content_max_access: "people",
    });

    expect(within(dialog).getByText(/see only its name/)).toBeTruthy();

    await chooseAccess(dialog, /Only you/);
    await waitFor(() =>
      expect(within(dialog).queryByText(/see only its name/)).toBeNull(),
    );
  });
});
