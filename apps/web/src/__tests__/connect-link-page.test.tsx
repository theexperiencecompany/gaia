// @vitest-environment jsdom
/**
 * Bot connect links: /connect/<code> moves the code into a cookie and redirects,
 * so no page URL that analytics records ever holds it. The /connect page shows
 * what the code connects without spending it; only Continue spends it.
 */

import { ApiError } from "@shared/api";
import type { ConnectLinkPreviewResponse } from "@shared/api/generated";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let cookieValue: string | undefined;
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) =>
      name === "gaia_connect_code" && cookieValue !== undefined
        ? { name, value: cookieValue }
        : undefined,
  }),
}));

vi.mock("@/lib/api/typed", () => ({
  api: { post: vi.fn() },
}));

vi.mock("@/lib/observability/reportToSentry", () => ({
  reportToSentry: vi.fn(),
}));

import { GET } from "@/app/connect/[code]/route";
import ConnectLinkPage from "@/app/connect/page";
import { api } from "@/lib/api/typed";
import { reportToSentry } from "@/lib/observability/reportToSentry";

const API_BASE = "https://api.example.test/api/v1/";
const PREVIEW: ConnectLinkPreviewResponse = {
  integration_id: "gmail",
  integration_name: "Gmail",
  icon_url: null,
  account_email: "ar***@heygaia.io",
};
const post = vi.mocked(api.post);

describe("GET /connect/<code>", () => {
  it("moves the code into an HttpOnly cookie and drops it from the URL", async () => {
    const response = await GET(new Request("https://heygaia.io/connect/c0de"), {
      params: Promise.resolve({ code: "c0de" }),
    });

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("https://heygaia.io/connect");
    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toContain("gaia_connect_code=c0de");
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("Path=/connect");
    expect(cookie).toContain("Secure");
  });
});

describe("ConnectLinkPage", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE);
    post.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    cookieValue = undefined;
  });

  it("names the integration and the masked account before Continue spends the code", async () => {
    cookieValue = "c0de";
    post.mockResolvedValue(PREVIEW);
    render(await ConnectLinkPage());

    expect(
      await screen.findByRole("heading", { name: "Connect Gmail to GAIA" }),
    ).toBeTruthy();
    expect(screen.getByText("ar***@heygaia.io")).toBeTruthy();
    expect(post).toHaveBeenCalledWith(
      "/api/v1/integrations/connect-link/preview",
      { body: { code: "c0de" }, silent: true },
    );
  });

  it("posts the cookie's code to the API's connect-link endpoint from Continue", async () => {
    cookieValue = "c0de";
    post.mockResolvedValue(PREVIEW);
    render(await ConnectLinkPage());

    const button = await screen.findByRole("button", {
      name: "Continue to Gmail",
    });
    const form = button.closest("form");
    expect(form?.getAttribute("method")).toBe("post");
    expect(form?.getAttribute("action")).toBe(
      "https://api.example.test/api/v1/integrations/connect-link",
    );
    expect(button.getAttribute("type")).toBe("submit");
    expect(form && new FormData(form).get("code")).toBe("c0de");
  });

  it("says the link expired, with no form, when no code arrived", async () => {
    render(await ConnectLinkPage());

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/expired or was already used/)).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });

  it("says the link expired, with no form, when the API no longer knows the code", async () => {
    cookieValue = "spent";
    post.mockRejectedValue(new ApiError("invalid_or_expired_link", 404));
    render(await ConnectLinkPage());

    expect(await screen.findByText(/expired or was already used/)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps Continue and reports the failure when the preview fails otherwise", async () => {
    cookieValue = "c0de";
    const failure = new ApiError("Too many requests", 429);
    post.mockRejectedValue(failure);
    render(await ConnectLinkPage());

    await waitFor(() => expect(reportToSentry).toHaveBeenCalledWith(failure));
    const button = screen.getByRole("button", { name: "Continue" });
    expect(
      button.closest("form") &&
        new FormData(button.closest("form") as HTMLFormElement).get("code"),
    ).toBe("c0de");
  });

  it("fails loud when the API base URL is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");

    await expect(ConnectLinkPage()).rejects.toThrow("NEXT_PUBLIC_API_BASE_URL");
  });
});
