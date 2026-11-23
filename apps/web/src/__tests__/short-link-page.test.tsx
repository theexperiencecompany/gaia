// @vitest-environment jsdom
/**
 * The /l/<slug> server page: metadata from /meta for everyone, the view only
 * for a real viewer, and the denial the server-side resolve answers.
 */
import { ApiError } from "@shared/api";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let userAgent = "Mozilla/5.0 (Macintosh)";
let host = "gaia.example.org";
vi.mock("next/headers", () => ({
  headers: async () => new Headers({ "user-agent": userAgent, host }),
}));
vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));
const openLinkInBrowser = vi.hoisted(() =>
  vi.fn(() => new Promise(() => undefined)),
);
vi.mock("@/features/short-links/api/linkViewerApi", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/short-links/api/linkViewerApi")
  >()),
  openLinkInBrowser,
}));

import ShortLinkPage, { generateMetadata } from "@/app/[locale]/l/[slug]/page";

const SLUG = "abcdefghijk";
const params = Promise.resolve({ slug: SLUG });

function respond(status: number, body: object) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  openLinkInBrowser.mockClear();
  userAgent = "Mozilla/5.0 (Macintosh)";
  host = "gaia.example.org";
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("generateMetadata", () => {
  it.each(["link_lookup_locked", "rate_limit_exceeded"])(
    "previews nothing for a viewer refused with %s, leaving the page to say why",
    async (code) => {
      fetchMock.mockResolvedValue(respond(429, { message: "slow down", code }));

      const metadata = await generateMetadata({ params });

      expect(metadata.title).toBe("GAIA");
      expect(metadata.robots).toEqual({ index: false, follow: false });
      expect(metadata.openGraph).toBeUndefined();
    },
  );

  it("indexes only an indexable link and points the preview at the generated card", async () => {
    fetchMock.mockResolvedValue(
      respond(200, {
        live: true,
        target_type: "todo_deliverable",
        access: "public",
        indexable: true,
        title: "Trip plan",
        description: "A todo from GAIA",
        image_url: null,
      }),
    );

    const metadata = await generateMetadata({ params });

    expect(String(fetchMock.mock.calls[0][0])).toBe(
      `http://localhost:8000/l/${SLUG}/meta`,
    );
    expect(metadata.title).toBe("Trip plan");
    expect(metadata.robots).toEqual({ index: true, follow: true });
    expect(metadata.openGraph).toMatchObject({
      siteName: "GAIA",
      // On the host that served the page, never GAIA Cloud's site URL: a self-host previews itself.
      images: [
        {
          url: `https://gaia.example.org/api/og/link?slug=${SLUG}`,
          width: 1200,
          height: 630,
        },
      ],
    });
    expect(metadata.twitter).toMatchObject({ card: "summary_large_image" });
  });

  it("uses the type's own image and keeps an unlisted link out of search", async () => {
    fetchMock.mockResolvedValue(
      respond(200, {
        live: true,
        target_type: "briefing",
        access: "unlisted",
        indexable: false,
        title: "Tuesday",
        description: "A brief from GAIA",
        image_url: "https://res.cloudinary.test/brief.jpg",
      }),
    );

    const metadata = await generateMetadata({ params });

    expect(metadata.robots).toEqual({ index: false, follow: false });
    expect(metadata.openGraph).toMatchObject({
      images: [{ url: "https://res.cloudinary.test/brief.jpg" }],
    });
  });
});

describe("ShortLinkPage", () => {
  it("gives a chat-preview bot the metadata only, never resolving the link", async () => {
    userAgent = "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)";

    expect(await ShortLinkPage({ params })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows a removed link's dead state without asking the browser", async () => {
    fetchMock.mockResolvedValue(
      respond(410, { message: "gone", code: "link_removed" }),
    );

    render(await ShortLinkPage({ params }));

    expect(
      screen.getByRole("heading", {
        name: "This link was removed for breaking GAIA's terms.",
      }),
    ).toBeTruthy();
    expect(openLinkInBrowser).not.toHaveBeenCalled();
  });

  it.each([
    [
      "link_revoked",
      "This link was turned off by the person who shared it. Ask them for a new one.",
    ],
    [
      "link_expired",
      "This link has expired. Ask the person who shared it for a new one.",
    ],
  ])(
    "hands a %s link to the browser, where only its owner still opens it",
    async (code, copy) => {
      fetchMock.mockResolvedValue(respond(410, { message: "gone", code }));
      openLinkInBrowser.mockRejectedValueOnce(
        new ApiError("gone", 410, { envelope: { message: "gone", code } }),
      );

      render(await ShortLinkPage({ params }));

      expect(openLinkInBrowser).toHaveBeenCalledWith(SLUG);
      expect(await screen.findByRole("heading", { name: copy })).toBeTruthy();
    },
  );

  it("hands a sign-in denial to the browser, which holds the session", async () => {
    fetchMock.mockResolvedValue(
      respond(401, { message: "sign in", code: "link_sign_in_required" }),
    );

    render(await ShortLinkPage({ params }));

    expect(openLinkInBrowser).toHaveBeenCalledWith(SLUG);
  });

  it("tells a viewer locked out for guessing links to wait", async () => {
    fetchMock.mockResolvedValue(
      respond(429, { message: "slow down", code: "link_lookup_locked" }),
    );

    render(await ShortLinkPage({ params }));

    expect(
      screen.getByRole("heading", {
        name: "Too many links that don't exist were opened from here. Try again in an hour.",
      }),
    ).toBeTruthy();
  });

  it("tells a viewer over the rate limit to wait a minute", async () => {
    fetchMock.mockResolvedValue(
      respond(429, { message: "slow down", code: "rate_limit_exceeded" }),
    );

    render(await ShortLinkPage({ params }));

    expect(
      screen.getByRole("heading", {
        name: "Too many links were opened from here. Try again in a minute.",
      }),
    ).toBeTruthy();
  });

  it("fails loud on an answer that is not a link denial", async () => {
    fetchMock.mockResolvedValue(
      respond(503, { message: "down", code: "service_unavailable" }),
    );

    await expect(ShortLinkPage({ params })).rejects.toThrow(
      "Short link resolve failed with 503",
    );
  });
});
