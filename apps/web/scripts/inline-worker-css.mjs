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
  const headers = new Headers(response.headers);
  headers.delete("content-length");
  return new Response(html, { status: response.status, headers });
}

export default {
  async fetch(request, env, ctx) {
    const response = await baseWorker.fetch(request, env, ctx);
    return inlineHtml(response, request, env);
  },
};
`);
console.log("inline-worker-css: wrapped .open-next/worker.js");
