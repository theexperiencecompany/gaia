import { describe, expect, it } from "vitest";

import { showsMarketingChrome } from "@/components/layouts/marketingChrome";

describe("marketing chrome around the auth pages", () => {
  it.each(["/login", "/signup"])(
    "is hidden on a self-hosted instance's %s",
    (pathname) => {
      expect(showsMarketingChrome(pathname, "local")).toBe(false);
    },
  );

  it.each(["/login", "/signup", "/pricing", "/"])(
    "stays on hosted GAIA's %s",
    (pathname) => {
      expect(showsMarketingChrome(pathname, null)).toBe(true);
      expect(showsMarketingChrome(pathname, "workos")).toBe(true);
    },
  );

  it("is always hidden on the desktop login handoff", () => {
    expect(showsMarketingChrome("/desktop-login", null)).toBe(false);
  });
});
