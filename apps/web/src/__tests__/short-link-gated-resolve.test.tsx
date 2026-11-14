// @vitest-environment jsdom
/**
 * People and owner links resolve in the browser, the only place the viewer's
 * session cookie exists; the denial it answers decides the page.
 */

import { ApiError } from "@shared/api";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));
vi.mock("@/features/chat/components/interface/RichContentRenderer", () => ({
  RichContentRenderer: ({ content }: { content: string }) => <p>{content}</p>,
}));

const resolveLinkInBrowser = vi.hoisted(() => vi.fn());
const recordShortLinkOpen = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock("@/features/short-links/api/linkViewerApi", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/short-links/api/linkViewerApi")
  >()),
  resolveLinkInBrowser,
  recordShortLinkOpen,
}));

import { GatedLinkView } from "@/features/short-links/components/GatedLinkView";

function denial(status: number, code: string, extra = {}) {
  return new ApiError("denied", status, {
    envelope: { message: "denied", code, ...extra },
  });
}

describe("GatedLinkView", () => {
  beforeEach(() => {
    resolveLinkInBrowser.mockReset();
    recordShortLinkOpen.mockClear();
  });

  it("asks a signed-out viewer to sign in and return to the link", async () => {
    resolveLinkInBrowser.mockRejectedValue(
      denial(401, "link_sign_in_required"),
    );
    render(<GatedLinkView slug="abcdefghijk" />);

    const signIn = await screen.findByRole("button", { name: "Sign in" });
    expect(signIn.getAttribute("href")).toBe(
      "/login?return_url=%2Fl%2Fabcdefghijk",
    );
    expect(resolveLinkInBrowser).toHaveBeenCalledWith("abcdefghijk");
    expect(recordShortLinkOpen).not.toHaveBeenCalled();
  });

  it("names the account a signed-in viewer without access is using", async () => {
    resolveLinkInBrowser.mockRejectedValue(
      denial(403, "link_forbidden", { signed_in_as: "sam@example.com" }),
    );
    render(<GatedLinkView slug="abcdefghijk" />);

    expect(
      await screen.findByText("You're signed in as sam@example.com."),
    ).toBeTruthy();
  });

  it("opens the link for a grantee and counts the open", async () => {
    resolveLinkInBrowser.mockResolvedValue({
      access: "people",
      target_type: "todo_deliverable",
      view: {
        target_type: "todo_deliverable",
        title: "Trip plan",
        completed: false,
        content: "Day one: Lisbon",
      },
      content: null,
      is_owner: false,
    });
    render(<GatedLinkView slug="abcdefghijk" />);

    expect(
      await screen.findByRole("heading", { name: "Trip plan" }),
    ).toBeTruthy();
    expect(screen.getByText("Day one: Lisbon")).toBeTruthy();
    expect(recordShortLinkOpen).toHaveBeenCalledWith("abcdefghijk");
  });
});
