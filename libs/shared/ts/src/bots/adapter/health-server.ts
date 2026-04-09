/**
 * Lightweight health check HTTP server for bot containers.
 *
 * Uses Node's built-in `http` module to avoid adding web framework
 * dependencies to the shared library. Exposes a single `GET /health`
 * endpoint that returns `{"status":"ok","platform":"<name>"}`.
 *
 * Started automatically by {@link BaseBotAdapter.boot} when the
 * `HEALTH_PORT` environment variable is set.
 *
 * @module
 */

import { createServer, type Server } from "node:http";
import type { PlatformName } from "../types";
import { type BotLogger, createBotLogger } from "../utils/logger";

/** Options for creating a health server. */
export interface HealthServerOptions {
  /** TCP port to listen on. */
  port: number;
  /** Platform name included in the health response. */
  platform: PlatformName;
  /**
   * Optional callback invoked on every `GET /health` request.
   * Return `false` to signal unhealthy (503). Defaults to healthy.
   */
  check?: () => boolean;
}

/**
 * Creates and starts a minimal HTTP health check server.
 *
 * @returns A `Server` handle that can be closed during shutdown.
 */
export function startHealthServer(
  options: HealthServerOptions,
): Promise<Server> {
  const { port, platform, check } = options;
  const logger: BotLogger = createBotLogger(platform, "health-server");

  return new Promise<Server>((resolve, reject) => {
    const server = createServer((req, res) => {
      if (req.method === "GET" && (req.url === "/health" || req.url === "/")) {
        const healthy = check ? check() : true;
        const status = healthy ? 200 : 503;
        const body = JSON.stringify({
          status: healthy ? "ok" : "unhealthy",
          platform,
        });
        res.writeHead(status, { "Content-Type": "application/json" });
        res.end(body);
        return;
      }

      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "not found" }));
    });

    server.on("error", (err) => {
      logger.error("health_server_error", undefined, err);
      reject(err);
    });

    server.listen(port, () => {
      logger.info("health_server_started", { port });
      resolve(server);
    });
  });
}
