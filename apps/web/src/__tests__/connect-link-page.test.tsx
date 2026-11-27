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
  headers: async () => new Headers(),
  cookies: async () => ({
    get: (name: string) =>
      name === "gaia_connect_code" && cookieValue !== undefined
        ? { name, value: cookieValue }
        : undefined,
  }),
}));

import type { ConnectLinkPreviewResponse } from "@shared/api/generated";

import { GET } from "@/app/connect/[code]/route";
import ConnectLinkPage from "@/app/connect/page";

const API_BASE = "https://api.example.test/api/v1/";
const PREVIEW: ConnectLinkPreviewResponse = {
  integration_id: "gmail",
  name: "Gmail",
  icon_url: null,
  account_email: "ar***@heygaia.io",
};

function answerPreview(status: number, body: unknown = PREVIEW) {
  const fetchMock = vi.fn(
    async () => new Response(JSON.stringify(body), { status }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

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
    vi.unstubAllGlobals();
    cookieValue = undefined;
  });

  it("names the integration and the masked account before Continue spends the code", async () => {
    cookieValue = "c0de";
    const fetchMock = answerPreview(200);
    render(await ConnectLinkPage());

    expect(screen.getByRole("heading").textContent).toBe(
      "Connect Gmail to GAIA",
    );
    expect(screen.getByText("ar***@heygaia.io")).toBeTruthy();
    const [url, init] = fetchMock.mock.calls[0] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe(
      "https://api.example.test/api/v1/integrations/connect-link/preview",
    );
    expect(init.method).toBe("POST");
    expect(String(init.body)).toBe("code=c0de");
  });

  it("posts the cookie's code to the API's connect-link endpoint from Continue", async () => {
    cookieValue = "c0de";
    answerPreview(200);
    render(await ConnectLinkPage());

    const button = screen.getByRole("button", { name: "Continue to Gmail" });
    const form = button.closest("form");
    expect(form?.getAttribute("method")).toBe("post");
    expect(form?.getAttribute("action")).toBe(
      "https://api.example.test/api/v1/integrations/connect-link",
    );
    expect(button.getAttribute("type")).toBe("submit");
    expect(form && new FormData(form).get("code")).toBe("c0de");
  });

  it("says the link expired, with no form, when no code arrived", async () => {
    const fetchMock = answerPreview(200);
    render(await ConnectLinkPage());

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/expired or was already used/)).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says the link expired, with no form, when the API no longer knows the code", async () => {
    cookieValue = "spent";
    answerPreview(404, { message: "invalid_or_expired_link" });
    render(await ConnectLinkPage());

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/expired or was already used/)).toBeTruthy();
  });

  it("fails loud when the preview fails for any other reason", async () => {
    cookieValue = "c0de";
    answerPreview(500, { message: "boom" });

    await expect(ConnectLinkPage()).rejects.toThrow("failed with 500");
  });

  it("fails loud when the API base URL is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");

    await expect(ConnectLinkPage()).rejects.toThrow("NEXT_PUBLIC_API_BASE_URL");
  });
});
