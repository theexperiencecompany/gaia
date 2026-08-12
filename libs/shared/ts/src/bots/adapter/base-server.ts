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

/** A shared HTTP server that all bot adapters can extend with custom routes. */
export class BotServer {
  /** The Hono app instance. Add routes here before calling {@link start}. */
  readonly app: Hono;

  private server: Server | null = null;
  private readonly port: number;
  private readonly platform: PlatformName;

  constructor(platform: PlatformName, port: number) {
    this.platform = platform;
    this.port = port;
    this.app = new Hono();

    // Default health endpoint — always available.
    this.app.get("/health", (c) =>
      c.json({ status: "ok", platform: this.platform }),
    );
  }

  /**
   * Starts listening on the configured port. Call after adding custom routes.
   *
   * Emits nothing of its own: this runs inside `BaseBotAdapter.boot()`'s
   * `bot_boot` boundary, which already carries `server_port` and turns a bind
   * failure into one failed event with the real error in errors[]. A
   * "server_started" line beside it would be the same fact, twice, untraceable.
   */
  async start(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const onError = (err: Error) => reject(err);

      this.server = serve({ fetch: this.app.fetch, port: this.port }, () => {
        this.server?.off("error", onError);
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
