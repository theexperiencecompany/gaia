import fs from "node:fs";
import path from "node:path";

const out = path.join(process.cwd(), ".open-next");
const worker = path.join(out, "worker.js");
const base = path.join(out, "worker.base.js");

if (!fs.existsSync(worker)) {
  console.error("inline-worker-css: .open-next/worker.js missing; run opennextjs-cloudflare build first");
  process.exit(1);
}
if (fs.readFileSync(worker, "utf8").includes("inline-worker-css")) {
  process.exit(0);
}
fs.copyFileSync(worker, base);

fs.writeFileSync(worker, `/* inline-worker-css: per-page stylesheet -> inline style */
import baseWorker from "./worker.base.js";
export * from "./worker.base.js";

const cssCache = new Map();

function rebase(css, href) {
  const baseUrl = new URL(href, "https://assets.local");
  css = css.replace(/url\\(\\s*(['"]?)([^'")]+)\\1\\s*\\)/g, (match, quote, url) => {
    if (/^(data:|https?:|\\/\\/|#)/.test(url)) return match;
    const resolved = new URL(url, baseUrl);
    return \`url(\${quote}\${resolved.pathname}\${resolved.search}\${quote})\`;
  });
  return css.replace(/@font-face\\s*\\{([^}]*)\\}/g, (match, body) =>
    body.includes("font-display") ? match : \`@font-face{font-display:swap;\${body}}\`
  );
}

async function cssFor(env, href) {
  if (cssCache.has(href)) return cssCache.get(href);
  const asset = await env.ASSETS.fetch(new Request(new URL(href, "https://assets.local"), { headers: { "accept-encoding": "identity" } }));
  if (!asset.ok) return null;
  const css = rebase(await asset.text(), href);
  cssCache.set(href, css);
  return css;
}

function repairAria(html) {
  const ids = new Set([...html.matchAll(/\\sid="([^"]+)"/g)].map((m) => m[1]));
  return html.replace(/\\saria-(describedby|labelledby|controls)="([^"]*)"/g, (match, attr, value) => {
    const kept = value.split(/\\s+/).filter((id) => ids.has(id));
    return kept.length ? " aria-" + attr + '="' + kept.join(" ") + '"' : "";
  });
}

function randomNonce() {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

const ENFORCED_CSP = "content-security-policy";
const REPORT_ONLY_CSP = "content-security-policy-report-only";
let reportedBadCspMode = false;

/** CSP_MODE (wrangler var) picks enforce or report-only; an unknown value stays report-only, the side that cannot break pages. */
function cspHeaderName(env) {
  if (env.CSP_MODE === "enforce") return ENFORCED_CSP;
  if (env.CSP_MODE !== "report-only" && !reportedBadCspMode) {
    reportedBadCspMode = true;
    console.error("inline-worker-css: CSP_MODE must be enforce or report-only, got " + env.CSP_MODE + "; serving report-only");
  }
  return REPORT_ONLY_CSP;
}

/** Nonce every script in this response (cached HTML included) and add the nonce to script-src, so 'unsafe-inline' no longer applies. */
function withScriptNonce(html, init, env) {
  const { headers } = init;
  const policy = headers.get(REPORT_ONLY_CSP) ?? headers.get(ENFORCED_CSP);
  // A response from WORKER_SELF_REFERENCE already passed through this wrapper and carries its nonce.
  if (!policy || policy.includes("'nonce-")) return new Response(html, init);
  const nonce = randomNonce();
  const noncedPolicy = policy
    .split(";")
    .map((directive) => (directive.trim().startsWith("script-src ") ? directive + " 'nonce-" + nonce + "'" : directive))
    .join(";");
  headers.delete(REPORT_ONLY_CSP);
  headers.delete(ENFORCED_CSP);
  headers.set(cspHeaderName(env), noncedPolicy);
  return new HTMLRewriter()
    .on("script", { element: (script) => script.setAttribute("nonce", nonce) })
    .transform(new Response(html, init));
}

async function inlineHtml(response, request, env) {
  const type = response.headers.get("content-type") || "";
  if (!type.includes("text/html")) return response;
  let html = await response.text();
  const tags = [...html.matchAll(/<link\\b[^>]*>/g)].map((m) => m[0]).filter((tag) => /rel="stylesheet"/.test(tag) && /href="[^"]+\\.css"/.test(tag));
  for (const tag of tags) {
    const href = /href="([^"]+\\.css)"/.exec(tag)[1];
    const css = await cssFor(env, href);
    if (css) html = html.split(tag).join(\`<style data-href="\${href}">\${css}</style>\`);
  }
  html = repairAria(html);
  const headers = new Headers(response.headers);
  const cc = headers.get("cache-control") || "";
  if (/s-maxage/i.test(cc) && !/max-age/i.test(cc) && !/no-store|private/i.test(cc)) {
    headers.set("cache-control", "public, max-age=60, " + cc.replace(/^public,\\s*/i, ""));
  }
  headers.delete("content-length");
  return withScriptNonce(html, { status: response.status, headers }, env);
}

export default {
  async fetch(request, env, ctx) {
    const { pathname } = new URL(request.url);
    if (pathname.startsWith("/_next/static/") || pathname.startsWith("/_next/image") || pathname.startsWith("/images/") || pathname.startsWith("/fonts/") || pathname.startsWith("/.well-known/") || pathname === "/favicon.ico" || pathname === "/robots.txt") return env.ASSETS.fetch(request);
    const response = await baseWorker.fetch(request, env, ctx);
    return inlineHtml(response, request, env);
  },
};
`);
console.log("inline-worker-css: wrapped .open-next/worker.js");
