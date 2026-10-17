import { beforeEach, describe, expect, it, vi } from "vitest";
import { siteConfig } from "@/lib/seo";

const get = vi.fn();
const createFallbackResponse = vi.fn();

vi.mock("@/lib/api/server", () => ({
  serverApi: () => ({ GET: get }),
  serverApiError: (response: Response) => ({
    message: `HTTP ${response.status}`,
  }),
}));
vi.mock("@/features/referrals/components/InviteLandingPage", () => ({
  InviteLandingPage: () => null,
}));
vi.mock("@/app/api/og/invite/inviteOgImage", () => ({
  renderInviteOgImage: vi.fn(),
}));
vi.mock("@/app/api/og/lib", () => ({
  createFallbackResponse,
  OG_HEIGHT: 630,
  OG_WIDTH: 1200,
}));

const { generateMetadata } = await import("./page");
const { default: InviteOgImage } = await import("./opengraph-image");

const params = Promise.resolve({ code: "aryan-k7f2" });

describe.each([
  [
    "the API is unreachable",
    () => get.mockRejectedValue(new TypeError("fetch failed")),
  ],
  [
    "the API answers with an error",
    () =>
      get.mockResolvedValue({
        data: undefined,
        error: { message: "unavailable" },
        response: new Response(null, { status: 503 }),
      }),
  ],
])("an invite preview when %s", (_, failResolve) => {
  beforeEach(() => {
    failResolve();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("still gets generic, unindexed page metadata", async () => {
    const metadata = await generateMetadata({ params });

    expect(metadata.title).toBe(siteConfig.name);
    expect(metadata.description).toBe(siteConfig.description);
    expect(metadata.robots).toEqual({ index: false, follow: true });
    expect(console.error).toHaveBeenCalled();
  });

  it("still gets the generic link-preview image", async () => {
    const fallback = new Response("fallback");
    createFallbackResponse.mockReturnValue(fallback);

    expect(await InviteOgImage({ params })).toBe(fallback);
    expect(createFallbackResponse).toHaveBeenCalledWith(siteConfig.name);
    expect(console.error).toHaveBeenCalled();
  });
});
