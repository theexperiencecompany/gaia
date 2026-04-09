/**
 * Shared HTTP server for all bot containers.
 *
 * Provides a Hono app with a built-in `/health` endpoint. Subclass adapters
 * can mount additional routes (e.g. WhatsApp's `/webhook`) on the same app
 * via {@link BotServer.app} before calling {@link BotServer.start}.
 *
 * One server per bot process. Started automatically by
 * {@link BaseBotAdapter.boot} on each adapter's default port.
 *
 * @module
 */

import type { Server } from "node:http";
import { serve } from "@hono/node-server";
import { Hono } from "hono";
import type { PlatformName } from "../types";
import { type BotLogger, createBotLogger } from "../utils/logger";

/** A shared HTTP server that all bot adapters can extend with custom routes. */
export class BotServer {
  /** The Hono app instance. Add routes here before calling {@link start}. */
  readonly app: Hono;

  private server: Server | null = null;
  private readonly port: number;
  private readonly platform: PlatformName;
  private readonly logger: BotLogger;

  constructor(platform: PlatformName, port: number) {
    this.platform = platform;
    this.port = port;
    this.logger = createBotLogger(platform, "server");
    this.app = new Hono();

    // Default health endpoint — always available.
    this.app.get("/health", (c) =>
      c.json({ status: "ok", platform: this.platform }),
    );
  }

  /** Starts listening on the configured port. Call after adding custom routes. */
  async start(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const onError = (err: Error) => {
        this.logger.error("server_error", undefined, err);
        reject(err);
      };

      this.server = serve({ fetch: this.app.fetch, port: this.port }, () => {
        this.server?.off("error", onError);
        this.logger.info("server_started", { port: this.port });
        resolve();
      }) as Server;

      this.server.once("error", onError);
    });
  }

  /** Gracefully closes the HTTP server. */
  async stop(): Promise<void> {
    if (!this.server) return;
    return new Promise<void>((resolve, reject) => {
      this.server!.close((err) => (err ? reject(err) : resolve()));
    }).then(() => {
      this.server = null;
    });
  }
}
