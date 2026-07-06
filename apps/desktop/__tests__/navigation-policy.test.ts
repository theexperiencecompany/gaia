/**
 * Tests for the main-window navigation policy (clickjacking / IPC-surface guard).
 *
 * The renderer shares the privileged preload bridge, so navigating the window to
 * an attacker origin would hand them our IPC surface. This policy decides which
 * navigations are allowed in-window, opened in the OS browser, or blocked
 * outright. A regression that lets a foreign origin navigate in-window, or hands
 * a non-http(s) scheme to the OS, must fail here.
 */

import { describe, expect, it } from "vitest";
import { classifyNavigation } from "../src/main/windows/navigation-policy";

const ALLOWED = new Set(["http://localhost:3000", "https://api.heygaia.io"]);

describe("classifyNavigation", () => {
  it("allows navigation to an allowed origin", () => {
    expect(classifyNavigation("http://localhost:3000/chat", ALLOWED)).toBe(
      "allow",
    );
    expect(classifyNavigation("https://api.heygaia.io/v1/me", ALLOWED)).toBe(
      "allow",
    );
  });

  it("opens a foreign http(s) origin externally instead of in-window", () => {
    expect(classifyNavigation("https://evil.example.com/", ALLOWED)).toBe(
      "open-external",
    );
    expect(classifyNavigation("http://phish.test/login", ALLOWED)).toBe(
      "open-external",
    );
  });

  it("treats a different port / scheme on the same host as foreign", () => {
    // Origin includes scheme + host + port — localhost:3001 is NOT localhost:3000.
    expect(classifyNavigation("http://localhost:3001/", ALLOWED)).toBe(
      "open-external",
    );
    // https vs http on an allowed host is a different origin.
    expect(classifyNavigation("https://localhost:3000/", ALLOWED)).toBe(
      "open-external",
    );
  });

  it.each([
    "mailto:hi@example.com",
    "javascript:alert(1)",
    "file:///etc/passwd",
    "gaia://deep/link",
    "data:text/html,<script>alert(1)</script>",
  ])("blocks non-http(s) scheme %s (never handed to the OS)", (url) => {
    expect(classifyNavigation(url, ALLOWED)).toBe("block");
  });

  it.each([
    "not a url",
    "http://",
    "://missing-scheme",
  ])("blocks malformed URL %s", (url) => {
    expect(classifyNavigation(url, ALLOWED)).toBe("block");
  });
});
