/** Every response carries the same security headers, whether the OpenNext worker or Workers Static Assets serves it. */
import { readFileSync } from "node:fs";
import path from "node:path";
import { getPathMatch } from "next/dist/shared/lib/router/utils/path-match";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

type Header = { key: string; value: string };
type NextHeaderRule = { source: string; headers: Header[] };

const SECURITY_HEADER_KEYS = [
  "content-security-policy",
  "content-security-policy-report-only",
  "permissions-policy",
  "referrer-policy",
  "reporting-endpoints",
  "strict-transport-security",
  "x-content-type-options",
  "x-frame-options",
];

const PATHS = [
  "/",
  "/about",
  "/login",
  "/marketplace/airtable",
  "/robots.txt",
  "/images/logo.png",
  "/_next/static/chunks/main.js",
  "/mcp-sandbox-proxy.html",
];

const SANDBOX_PROXY = "/mcp-sandbox-proxy.html";

function securityOnly(headers: Map<string, string>): Record<string, string> {
  return Object.fromEntries(
    [...headers].filter(([key]) => SECURITY_HEADER_KEYS.includes(key)),
  );
}

/** Next applies every matching rule in order; a later rule's key overrides an earlier one. */
function workerHeaders(
  rules: NextHeaderRule[],
  pathname: string,
): Map<string, string> {
  const headers = new Map<string, string>();
  for (const rule of rules) {
    const match = getPathMatch(rule.source, {
      strict: true,
      removeUnnamedParams: true,
    });
    if (match(pathname) === false) continue;
    for (const { key, value } of rule.headers) {
      headers.set(key.toLowerCase(), value);
    }
  }
  return headers;
}

type StaticRule = {
  pattern: RegExp;
  set: [string, string][];
  unset: string[];
};

/** Parse a Workers Static Assets _headers file into its rules. */
function parseStaticHeaders(file: string): StaticRule[] {
  const rules: StaticRule[] = [];
  for (const line of file.split("\n")) {
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    if (!/^\s/.test(line)) {
      const escaped = line
        .trim()
        .replace(/[.+?^${}()|[\]\\]/g, "\\$&")
        .replaceAll("*", ".*");
      rules.push({ pattern: new RegExp(`^${escaped}$`), set: [], unset: [] });
      continue;
    }
    const rule = rules.at(-1);
    if (!rule) throw new Error(`header line before any path: ${line}`);
    const entry = line.trim();
    if (entry.startsWith("!")) {
      rule.unset.push(entry.slice(1).trim().toLowerCase());
      continue;
    }
    const colon = entry.indexOf(":");
    rule.set.push([
      entry.slice(0, colon).trim().toLowerCase(),
      entry.slice(colon + 1).trim(),
    ]);
  }
  return rules;
}

/** The asset worker's semantics: per matching rule, detach then set; a key set twice is comma-joined. */
function staticHeaders(
  rules: StaticRule[],
  pathname: string,
): Map<string, string> {
  const headers = new Map<string, string>();
  const seen = new Set<string>();
  for (const rule of rules) {
    if (!rule.pattern.test(pathname)) continue;
    for (const key of rule.unset) headers.delete(key);
    for (const [key, value] of rule.set) {
      const existing = headers.get(key);
      headers.set(
        key,
        seen.has(key) && existing !== undefined
          ? `${existing}, ${value}`
          : value,
      );
      seen.add(key);
    }
  }
  return headers;
}

const POSTHOG_PROJECT_TOKEN = "phc_test_token";
// wrangler's _headers parser drops longer lines and every rule past the 100th.
const MAX_STATIC_HEADER_LINE = 2000;
const MAX_STATIC_HEADER_RULES = 100;

let workerRules: NextHeaderRule[];
let staticFile: string;
let staticRules: StaticRule[];

beforeAll(async () => {
  // The header modules read the build env at import, as next build and cf:build do.
  vi.stubEnv("NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN", POSTHOG_PROJECT_TOKEN);
  const { default: nextConfig } = await import("../../next.config.mjs");
  const { renderStaticHeaders } = await import("../../security-headers.mjs");
  if (!nextConfig.headers)
    throw new Error("next.config.mjs defines no headers()");
  workerRules = await nextConfig.headers();
  staticFile = renderStaticHeaders(
    readFileSync(path.join(process.cwd(), "public", "_headers"), "utf8"),
  );
  staticRules = parseStaticHeaders(staticFile);
});

afterAll(() => {
  vi.unstubAllEnvs();
});

describe("security headers", () => {
  it.each(PATHS)(
    "%s gets identical headers from the worker and the static assets",
    (pathname) => {
      expect(securityOnly(staticHeaders(staticRules, pathname))).toEqual(
        securityOnly(workerHeaders(workerRules, pathname)),
      );
    },
  );

  it.each(PATHS.filter((p) => p !== SANDBOX_PROXY))(
    "%s refuses to be framed and pins HTTPS",
    (pathname) => {
      for (const headers of [
        workerHeaders(workerRules, pathname),
        staticHeaders(staticRules, pathname),
      ]) {
        expect(headers.get("x-frame-options")).toBe("DENY");
        expect(headers.get("x-content-type-options")).toBe("nosniff");
        expect(headers.get("referrer-policy")).toBe(
          "strict-origin-when-cross-origin",
        );
        expect(headers.get("strict-transport-security")).toBe(
          "max-age=31536000; includeSubDomains",
        );
        expect(headers.get("permissions-policy")).toContain("camera=()");
        expect(headers.get("content-security-policy-report-only")).toContain(
          "frame-ancestors 'none'",
        );
      }
    },
  );

  it("lets the app frame its own MCP sandbox proxy and nothing else", () => {
    for (const headers of [
      workerHeaders(workerRules, SANDBOX_PROXY),
      staticHeaders(staticRules, SANDBOX_PROXY),
    ]) {
      expect(headers.get("x-frame-options")).toBe("SAMEORIGIN");
      expect(headers.get("content-security-policy")).toBe(
        "frame-ancestors 'self'",
      );
      expect(headers.has("content-security-policy-report-only")).toBe(false);
    }
  });

  it("reports CSP violations to the PostHog project", () => {
    const sink = `https://us.i.posthog.com/report/?token=${POSTHOG_PROJECT_TOKEN}`;
    const headers = workerHeaders(workerRules, "/");
    expect(headers.get("content-security-policy-report-only")).toContain(
      `report-uri ${sink}; report-to posthog`,
    );
    expect(headers.get("reporting-endpoints")).toBe(`posthog="${sink}"`);
  });

  it("keeps the static cache rules and stays inside wrangler's _headers limits", () => {
    expect(
      staticHeaders(staticRules, "/_next/static/chunks/main.js").get(
        "cache-control",
      ),
    ).toBe("public, max-age=31536000, immutable");
    expect(staticRules.length).toBeLessThanOrEqual(MAX_STATIC_HEADER_RULES);
    for (const line of staticFile.split("\n")) {
      expect(line.trim().length).toBeLessThanOrEqual(MAX_STATIC_HEADER_LINE);
    }
  });
});
