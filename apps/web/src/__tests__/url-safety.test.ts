/**
 * Security tests for the shared link/redirect sanitizer.
 *
 * `sanitizeRedirectUrl` guards every backend-/LLM-driven link sink (notification
 * deep links, OpenUI timeline links, etc.). If a future edit lets a
 * `javascript:`/`data:` scheme or a protocol-relative `//host` through, one of
 * these assertions must fail.
 */
import { describe, expect, it } from "vitest";
import {
  isAppLink,
  isSafeInternalPath,
  sanitizeRedirectUrl,
} from "@/lib/url-safety";

describe("sanitizeRedirectUrl", () => {
  it("allows safe absolute http(s) and mailto URLs unchanged", () => {
    expect(sanitizeRedirectUrl("https://example.com/path")).toBe(
      "https://example.com/path",
    );
    expect(sanitizeRedirectUrl("http://example.com")).toBe(
      "http://example.com",
    );
    expect(sanitizeRedirectUrl("mailto:hi@example.com")).toBe(
      "mailto:hi@example.com",
    );
  });

  it("allows safe internal relative paths", () => {
    expect(sanitizeRedirectUrl("/dashboard")).toBe("/dashboard");
    expect(sanitizeRedirectUrl("/settings/profile?tab=1")).toBe(
      "/settings/profile?tab=1",
    );
  });

  it.each([
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "  javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "blob:https://example.com/uuid",
  ])("blocks dangerous scheme %s", (url) => {
    expect(sanitizeRedirectUrl(url)).toBeNull();
  });

  it.each(["//evil.com", "/\\evil.com", "\\\\evil.com"])(
    "blocks protocol-relative / backslash open-redirect %s",
    (url) => {
      expect(sanitizeRedirectUrl(url)).toBeNull();
    },
  );

  it("blocks malformed URLs", () => {
    expect(sanitizeRedirectUrl("ht!tp://://")).toBeNull();
    expect(sanitizeRedirectUrl("not a url")).toBeNull();
  });
});

describe("isSafeInternalPath", () => {
  it("accepts a single leading slash", () => {
    expect(isSafeInternalPath("/todos")).toBe(true);
    expect(isSafeInternalPath("/a/b/c")).toBe(true);
  });

  it("accepts an absolute path with a query string", () => {
    expect(isSafeInternalPath("/settings?tab=1")).toBe(true);
  });

  it.each([
    "//evil.com",
    "/\\evil.com",
    "/\t/evil.com", // whitespace-smuggled protocol-relative
    "https://evil.com",
    "todos",
    "",
  ])("rejects non-same-origin path %s", (path) => {
    expect(isSafeInternalPath(path)).toBe(false);
  });
});

describe("isAppLink", () => {
  const origin = "https://heygaia.io";

  it("keeps the API's absolute integrations link inside the app", () => {
    expect(isAppLink("https://heygaia.io/integrations", origin)).toBe(true);
    expect(
      isAppLink("https://heygaia.io/integrations?connect=gmail", origin),
    ).toBe(true);
  });

  it("treats a same-origin path as internal even before the origin is known", () => {
    expect(isAppLink("/integrations", "")).toBe(true);
    expect(isAppLink("//evil.example/integrations", "")).toBe(false);
  });

  it("sends every other origin to a new tab", () => {
    expect(isAppLink("https://docs.heygaia.io/setup", origin)).toBe(false);
    expect(
      isAppLink("https://heygaia.io.evil.example/integrations", origin),
    ).toBe(false);
    expect(isAppLink("mailto:hi@heygaia.io", origin)).toBe(false);
    expect(isAppLink("not a url", origin)).toBe(false);
  });
});
