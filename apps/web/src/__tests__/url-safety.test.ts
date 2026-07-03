/**
 * Security tests for the shared link/redirect sanitizer.
 *
 * `sanitizeRedirectUrl` guards every backend-/LLM-driven link sink (notification
 * deep links, OpenUI timeline links, etc.). If a future edit lets a
 * `javascript:`/`data:` scheme or a protocol-relative `//host` through, one of
 * these assertions must fail.
 */
import { describe, expect, it } from "vitest";
import { isSafeInternalPath, sanitizeRedirectUrl } from "@/lib/url-safety";

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

  it.each([
    "//evil.com",
    "/\\evil.com",
    "\\\\evil.com",
  ])("blocks protocol-relative / backslash open-redirect %s", (url) => {
    expect(sanitizeRedirectUrl(url)).toBeNull();
  });

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
