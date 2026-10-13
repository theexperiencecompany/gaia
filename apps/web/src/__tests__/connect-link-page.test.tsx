// @vitest-environment jsdom
/**
 * Bot connect links: /connect/<code> moves the code into a cookie and redirects,
 * so no page URL that analytics records ever holds it, and nothing is spent
 * until the /connect page's Continue form posts the code to the API.
 */

import { render, screen } from "@testing-library/react";
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
// The matcher is plain config; the next-intl handler it would wrap needs Next's server runtime.
vi.mock("next-intl/middleware", () => ({ default: () => () => undefined }));

import { GET } from "@/app/connect/[code]/route";
import ConnectLinkPage from "@/app/connect/page";
import { config } from "@/middleware";

const API_BASE = "https://api.example.test/api/v1/";

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
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    cookieValue = undefined;
  });

  it("posts the cookie's code to the API's connect-link endpoint from Continue", async () => {
    cookieValue = "c0de";
    render(await ConnectLinkPage());

    const button = screen.getByRole("button", { name: "Continue" });
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

    expect(screen.queryByRole("button", { name: "Continue" })).toBeNull();
    expect(screen.getByText(/expired or was already used/)).toBeTruthy();
  });

  it("fails loud when the API base URL is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");

    await expect(ConnectLinkPage()).rejects.toThrow("NEXT_PUBLIC_API_BASE_URL");
  });
});

describe("middleware matcher", () => {
  const matches = (path: string) =>
    config.matcher.some((pattern) => new RegExp(`^${pattern}$`).test(path));

  it("leaves /connect to its own analytics-free layout instead of the locale tree", () => {
    expect(matches("/connect/c0de")).toBe(false);
    expect(matches("/connect")).toBe(false);
    expect(matches("/integrations")).toBe(true);
  });
});
