/** The generated edge worker nonces inline scripts only, and leaves a policy without script-src exactly as the app sent it. */
import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { Miniflare } from "miniflare";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const SITE_POLICY = "default-src 'self'; script-src 'self' 'unsafe-inline'";
const PROXY_POLICY = "frame-ancestors 'self'";
const UNLISTED_SCRIPT = "https://unlisted.example/payload.js";

// Stands in for OpenNext's worker: the site page carries the report-only site
// policy, the MCP sandbox proxy only its enforced framing policy.
const BASE_WORKER = `
const PAGE = '<html><head><script>self.inline = 1</script><script src="${UNLISTED_SCRIPT}"></script></head><body></body></html>';
export default {
  async fetch(request) {
    const { pathname } = new URL(request.url);
    const headers = new Headers({ "content-type": "text/html; charset=utf-8" });
    if (pathname === "/mcp-sandbox-proxy.html") {
      headers.set("content-security-policy", ${JSON.stringify(PROXY_POLICY)});
    } else {
      headers.set("content-security-policy-report-only", ${JSON.stringify(SITE_POLICY)});
    }
    return new Response(PAGE, { headers });
  },
};
`;

let workDir: string;
const workers: Record<string, Miniflare> = {};

beforeAll(() => {
  workDir = mkdtempSync(path.join(tmpdir(), "inline-worker-csp-"));
  const openNext = path.join(workDir, ".open-next");
  mkdirSync(openNext);
  writeFileSync(path.join(openNext, "worker.js"), BASE_WORKER);
  execFileSync(
    process.execPath,
    [path.join(process.cwd(), "scripts/inline-worker-css.mjs")],
    { cwd: workDir },
  );
  for (const mode of ["enforce", "report-only"]) {
    workers[mode] = new Miniflare({
      compatibilityDate: "2026-01-01",
      modulesRoot: openNext,
      modules: ["worker.js", "worker.base.js"].map((file) => ({
        type: "ESModule" as const,
        path: path.join(openNext, file),
        contents: readFileSync(path.join(openNext, file), "utf8"),
      })),
      bindings: { CSP_MODE: mode },
    });
  }
});

afterAll(async () => {
  await Promise.all(Object.values(workers).map((worker) => worker.dispose()));
  rmSync(workDir, { recursive: true, force: true });
});

describe("inline-worker-css CSP", () => {
  it.each(["enforce", "report-only"])(
    "keeps the sandbox proxy's enforced frame-ancestors untouched under CSP_MODE=%s",
    async (mode) => {
      const response = await workers[mode].dispatchFetch(
        "http://localhost/mcp-sandbox-proxy.html",
      );
      const html = await response.text();

      expect(response.headers.get("content-security-policy")).toBe(
        PROXY_POLICY,
      );
      expect(response.headers.has("content-security-policy-report-only")).toBe(
        false,
      );
      expect(html).not.toContain("nonce=");
    },
  );

  it("nonces the inline script but not an unlisted external script", async () => {
    const response = await workers.enforce.dispatchFetch("http://localhost/");
    const html = await response.text();
    const nonce = response.headers
      .get("content-security-policy")
      ?.match(/'nonce-([^']+)'/)?.[1];

    expect(nonce).toBeTruthy();
    expect(html).toContain(`<script nonce="${nonce}">self.inline = 1</script>`);
    expect(html).toContain(`<script src="${UNLISTED_SCRIPT}"></script>`);
  });
});
