#!/usr/bin/env node
/**
 * Refuse to score a preview that is not the real Cloudflare worker.
 *
 * `next start` skips cf:build (no inlined CSS, no nonce CSP), so only `pnpm preview`
 * matches production; this exits non-zero with the reason when the target is not that.
 * Usage: node scripts/verify-worker-preview.mjs [base-url]
 */
const BASE = process.argv[2] ?? process.env.SMOKE_BASE_URL ?? "http://localhost:8788";

const failures = [];

function fail(msg) {
  failures.push(msg);
}

const res = await fetch(BASE, { redirect: "manual" }).catch((e) => {
  console.error(`[verify-worker-preview] ${BASE} unreachable: ${e.message}`);
  process.exit(2);
});

if (res.status !== 200) {
  fail(`base returned ${res.status}, expected 200`);
}

const html = await res.text();

// 1. The worker must have served the HTML, not a static asset pass-through of a
//    pre-rendered file with no headers.
const via = res.headers.get("x-opennext") ?? res.headers.get("server");
// CSP_MODE decides which of the two the worker sends.
const csp =
  res.headers.get("content-security-policy") ??
  res.headers.get("content-security-policy-report-only") ??
  "";
if (!csp) {
  fail(
    "no Content-Security-Policy header — inline-worker-css.mjs did not run, so " +
      "this is `next start`, not the worker",
  );
}

// 2. The nonce CSP only exists once the worker inlines its styles. A build with
//    external stylesheet links is the un-inlined one.
const styleLinks = [...html.matchAll(/<link[^>]+rel="stylesheet"[^>]*>/g)].length;
const inlineStyle = /<style[^>]*>/.test(html);
if (!inlineStyle && styleLinks > 0) {
  fail(
    `HTML carries ${styleLinks} external stylesheet link(s) and no inline <style> — ` +
      "cf:build did not inline worker CSS",
  );
}

// 3. A nonce that never appears in the markup means the policy is decorative.
const nonceHeader = csp.match(/'nonce-([^']+)'/)?.[1];
if (nonceHeader) {
  if (!html.includes(nonceHeader)) {
    fail(`CSP nonce ${nonceHeader} does not appear in the HTML`);
  }
} else if (/script-src[^;]*'unsafe-inline'/.test(csp)) {
  fail("script-src still allows 'unsafe-inline' — nonce injection did not apply");
}

if (failures.length > 0) {
  console.error(
    [
      `[verify-worker-preview] refusing to score ${BASE}:`,
      ...failures.map((f) => `  - ${f}`),
      "",
      "Boot the real preview first:  pnpm preview   (apps/web)",
      "then:  SMOKE_BASE_URL=" + BASE + " scripts/ci/smoke-web.sh squirrel",
    ].join("\n"),
  );
  process.exit(1);
}

console.log(
  `[verify-worker-preview] ${BASE} is the worker build (${via ?? "opennext"}): ` +
    `CSP nonce present, CSS inlined, ${styleLinks} external stylesheet(s).`,
);
