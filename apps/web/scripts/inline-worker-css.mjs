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
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

async function sha256Base64(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  const bytes = new Uint8Array(digest);
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

async function nonceCsp(html, headers) {
  const existing = headers.get("content-security-policy") || "";
  if (existing.includes("nonce-")) return html;
  const nonce = randomNonce();
  html = html.replace(/<script(?![^>]*\ssrc=)([^>]*)>/g, (m, attrs) =>
    attrs.includes("nonce=") ? m : "<script" + attrs + " nonce=\\\"" + nonce + "\\\">");
  html = html.replace(/<style([^>]*)>/g, (m, attrs) =>
    attrs.includes("nonce=") ? m : "<style" + attrs + " nonce=\\\"" + nonce + "\\\">");
  const values = new Set();
  html.replace(/\sstyle="([^"]*)"/g, (m, v) => {
    values.add(v);
    return m;
  });
  const hashes = [];
  for (const v of values) hashes.push("'sha256-" + (await sha256Base64(v)) + "'");
  const csp = headers.get("content-security-policy");
  if (csp) {
    let next = csp.split("'unsafe-inline'").join("'unsafe-hashes'");
    next = next.replace(/(script-src[^;]*)/, "$1 'nonce-" + nonce + "'");
    next = next.replace(/(style-src[^;]*)/, "$1 'nonce-" + nonce + "' " + hashes.join(" "));
    headers.set("content-security-policy", next);
  }
  return html;
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
  html = await nonceCsp(html, headers);
  headers.delete("content-length");
  return new Response(html, { status: response.status, headers });
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
