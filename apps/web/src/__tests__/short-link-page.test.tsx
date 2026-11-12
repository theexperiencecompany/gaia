// @vitest-environment jsdom
/**
 * The /l/<slug> server page: metadata from /meta for everyone, the view only
 * for a real viewer, and the denial the server-side resolve answers.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let userAgent = "Mozilla/5.0 (Macintosh)";
vi.mock("next/headers", () => ({
  headers: async () => new Headers({ "user-agent": userAgent }),
}));
vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));
const resolveLinkInBrowser = vi.hoisted(() =>
  vi.fn(() => new Promise(() => undefined)),
);
vi.mock("@/features/short-links/api/linkViewerApi", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/short-links/api/linkViewerApi")
  >()),
  resolveLinkInBrowser,
  recordShortLinkOpen: () => Promise.resolve(),
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
  userAgent = "Mozilla/5.0 (Macintosh)";
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("generateMetadata", () => {
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
      images: [{ url: `/api/og/link?slug=${SLUG}`, width: 1200, height: 630 }],
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

  it("shows a revoked link's dead state", async () => {
    fetchMock.mockResolvedValue(
      respond(410, { message: "gone", code: "link_revoked" }),
    );

    render(await ShortLinkPage({ params }));

    expect(
      screen.getByRole("heading", {
        name: "This link was turned off by the person who shared it. Ask them for a new one.",
      }),
    ).toBeTruthy();
  });

  it("hands a sign-in denial to the browser, which holds the session", async () => {
    fetchMock.mockResolvedValue(
      respond(401, { message: "sign in", code: "link_sign_in_required" }),
    );

    render(await ShortLinkPage({ params }));

    expect(resolveLinkInBrowser).toHaveBeenCalledWith(SLUG);
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

  it("fails loud on an answer that is not a link denial", async () => {
    fetchMock.mockResolvedValue(
      respond(503, { message: "down", code: "service_unavailable" }),
    );

    await expect(ShortLinkPage({ params })).rejects.toThrow(
      "Short link resolve failed with 503",
    );
  });
});
