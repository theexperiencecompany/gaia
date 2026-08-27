// nx-cache-server — minimal Nx self-hosted remote cache (nx.dev/docs/kb/self-hosted-caching).
//
// Why this exists: the per-runner local Nx cache is a SQLite database, so it
// is keyed per runner instance to avoid four concurrent jobs sharing one DB
// file. That makes a task computed on gaia-home-2 invisible to gaia-home-3.
// This server is the shared tier: HTTP is the concurrency boundary, so every
// instance (and, if ever exposed over Tailscale, developer laptops) reads and
// writes one store safely. Zero dependencies — Node's http module only.
//
// Spec: PUT /v1/cache/{hash} (octet-stream, Content-Length) → 200 | 401 | 403 | 409
//       GET /v1/cache/{hash}                                 → 200 | 403 | 404
//       Authorization: Bearer <token>
//
// Storage is size-bounded (NX_CACHE_MAX_BYTES, LRU on access time), never
// age-bounded: an age rule leaves the steady-state size up to the ingest rate.
import http from "node:http";
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";

const DIR = process.env.NX_CACHE_DIR || `${process.env.HOME}/ci-cache/nx-remote`;
const PORT = Number(process.env.NX_CACHE_PORT || 4222);
const HOST = process.env.NX_CACHE_HOST || "127.0.0.1"; // loopback only unless deliberately widened
const TOKEN = process.env.NX_CACHE_TOKEN || "";
const MAX_BYTES = Number(process.env.NX_CACHE_MAX_BYTES || 8 * 1024 ** 3); // 8 GiB
const HASH_RE = /^[A-Za-z0-9_-]{1,128}$/;

if (!TOKEN) { console.error("NX_CACHE_TOKEN is required"); process.exit(2); }
fs.mkdirSync(DIR, { recursive: true });

const stats = { hits: 0, misses: 0, puts: 0, conflicts: 0, evicted: 0, bytes: 0 };
const entryPath = (h) => path.join(DIR, `${h}.tar`);

async function totalBytes() {
  let n = 0;
  for (const f of await fsp.readdir(DIR)) if (f.endsWith(".tar")) n += (await fsp.stat(path.join(DIR, f))).size;
  return n;
}
// LRU by atime (touched on every GET); evict oldest until under budget.
async function evictIfNeeded() {
  let used = await totalBytes();
  if (used <= MAX_BYTES) return;
  const files = [];
  for (const f of await fsp.readdir(DIR)) {
    if (!f.endsWith(".tar")) continue;
    const st = await fsp.stat(path.join(DIR, f));
    files.push({ f, size: st.size, atime: st.atimeMs });
  }
  files.sort((a, b) => a.atime - b.atime);
  for (const e of files) {
    if (used <= MAX_BYTES * 0.9) break;
    await fsp.rm(path.join(DIR, e.f), { force: true });
    used -= e.size; stats.evicted++;
  }
}

function authorized(req) {
  const h = req.headers.authorization || "";
  return h === `Bearer ${TOKEN}`;
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.url === "/healthz") { res.writeHead(200); return res.end("ok"); }
    if (req.url === "/stats") { res.writeHead(200, { "content-type": "application/json" }); return res.end(JSON.stringify({ ...stats, bytes: await totalBytes(), max_bytes: MAX_BYTES })); }
    const m = req.url.match(/^\/v1\/cache\/([^/?]+)$/);
    if (!m) { res.writeHead(404); return res.end(); }
    if (!authorized(req)) { res.writeHead(401); return res.end("Missing or invalid authentication token"); }
    const hash = decodeURIComponent(m[1]);
    if (!HASH_RE.test(hash)) { res.writeHead(400); return res.end("bad hash"); }
    const file = entryPath(hash);

    if (req.method === "GET") {
      let st;
      try { st = await fsp.stat(file); } catch { stats.misses++; res.writeHead(404); return res.end(); }
      const now = new Date();
      fsp.utimes(file, now, st.mtime).catch(() => {}); // touch atime for LRU
      stats.hits++;
      res.writeHead(200, { "content-type": "application/octet-stream", "content-length": st.size });
      return fs.createReadStream(file).pipe(res);
    }

    if (req.method === "PUT") {
      if (fs.existsSync(file)) { stats.conflicts++; req.resume(); res.writeHead(409); return res.end("Cannot override an existing record"); }
      // write to a temp name, rename on completion → a reader never sees a partial tar
      const tmp = `${file}.${process.pid}.${Date.now()}.part`;
      const out = fs.createWriteStream(tmp);
      await new Promise((ok, err) => { req.pipe(out); out.on("finish", ok); out.on("error", err); req.on("error", err); });
      try { await fsp.rename(tmp, file); } catch { await fsp.rm(tmp, { force: true }); stats.conflicts++; res.writeHead(409); return res.end(); }
      stats.puts++;
      res.writeHead(200); res.end();
      evictIfNeeded().catch((e) => console.error("evict:", e));
      return;
    }
    res.writeHead(405); res.end();
  } catch (e) {
    console.error(e); if (!res.headersSent) res.writeHead(500); res.end();
  }
});
server.listen(PORT, HOST, () => console.log(`nx-cache-server listening on http://${HOST}:${PORT} dir=${DIR} max=${(MAX_BYTES / 1024 ** 3).toFixed(1)}GiB`));
