// Capture proxy: logs every request fx sends, returns a minimal canned SSE response.
// Run: node capture-proxy.mjs
// Then: FX_GATEWAY_BASE_URL=http://localhost:4319 fx
import http from "node:http";
import fs from "node:fs";

const PORT = 4319;
const LOG = "/tmp/fx-gateway-capture.log";
const out = fs.createWriteStream(LOG, { flags: "w" });
const log = (...args) => {
  const line = args.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" ");
  out.write(line + "\n");
  console.log(line);
};

const server = http.createServer((req, res) => {
  let body = "";
  req.on("data", (c) => (body += c.toString()));
  req.on("end", () => {
    log("\n========== REQUEST ==========");
    log("METHOD:", req.method);
    log("URL:", req.url);
    log("HEADERS:", req.headers);
    try {
      log("BODY (parsed):", JSON.parse(body));
    } catch {
      log("BODY (raw):", body);
    }
    log("=============================\n");

    // Canned responses by endpoint
    if (req.url.includes("/models")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ models: [{ id: "stealth/ox-alpha", name: "Ox Alpha" }] }));
      return;
    }
    if (req.url.includes("/credits")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ balance: 999 }));
      return;
    }
    // Chat endpoint: return minimal SSE
    res.writeHead(200, {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      connection: "keep-alive",
    });
    const canned = [
      { type: "start" },
      { type: "text-delta", textDelta: "Hello from capture proxy. Model: " },
      { type: "text-delta", textDelta: (req.headers["x-ai-gateway-model"] || req.headers["x-vercel-ai-gateway-model"] || "unknown") },
      { type: "finish" },
    ];
    for (const evt of canned) {
      res.write(`data: ${JSON.stringify(evt)}\n\n`);
    }
    res.write("data: [DONE]\n\n");
    res.end();
  });
});

server.listen(PORT, "127.0.0.1", () => {
  log(`Capture proxy on http://127.0.0.1:${PORT}`);
  log(`Logging to ${LOG}`);
});
