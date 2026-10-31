/** The NEXT_LOCALE cookie the middleware sets on translated routes is Secure. */
import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import middleware from "@/middleware";

describe("locale cookie", () => {
  it("is Secure on a translated route", async () => {
    const request = new NextRequest("https://heygaia.io/de/alternative-to", {
      headers: { host: "heygaia.io", "accept-language": "en" },
    });

    const setCookie = (await middleware(request)).headers.get("set-cookie");

    expect(setCookie).toMatch(/^NEXT_LOCALE=de;/);
    // next-intl rewrites this cookie from JS on client locale switches, so it cannot be HttpOnly.
    expect(setCookie?.toLowerCase()).toContain("secure");
  });
});
