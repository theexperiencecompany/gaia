#!/usr/bin/env node
/**
 * Refuse to score a preview that is not the real Cloudflare worker.
 *
 * `scripts/ci/smoke-web.sh audit-build` starts `next start`, which never runs
 * `cf:build` and therefore never runs `inline-worker-css.mjs`. Squirrel then
 * measures a site that does not exist in production: no inlined CSS, no nonce
 * CSP, no worker-served HTML. That produced scores that could not be
 * reproduced against the deploy.
 *
 * The honest target is `pnpm preview` (opennextjs-cloudflare preview): same
 * worker bundle, same asset pass-through, same CSP as production. This asserts
 * the preview really is that, and exits non-zero with the reason if not, so a
 * number is never reported for the wrong build.
 *
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
if (!res.headers.get("content-security-policy")) {
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
const csp = res.headers.get("content-security-policy") ?? "";
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
