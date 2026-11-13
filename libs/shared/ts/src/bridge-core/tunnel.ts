// The outbound tunnel: one WebSocket from this machine to GAIA, over which the
// cloud opens MCP sessions to our local servers and relays JSON-RPC frames. No
// inbound ports. Reconnects with jittered backoff; refreshes the connect token
// each dial (and rotates the stored refresh credential).

import { randomInt } from "node:crypto";
import type { JSONRPCMessage } from "@modelcontextprotocol/sdk/types.js";
import WebSocket from "ws";
import { ApiError } from "./api.js";
import { loadConfig, removeServer } from "./config.js";
import type { Credentials } from "./config.types.js";
import {
  FRAME,
  RECONNECT_MAX_MS,
  RECONNECT_MIN_MS,
  RECONNECT_SPREAD_MS,
} from "./constants.js";
import { bridgeLogger } from "./env.js";
import { runDeviceExec } from "./exec.js";
import { rotateCredentials } from "./rotation-lock.js";
import { openServerSession, type ServerSession } from "./servers.js";

interface Frame {
  t: string;
  sid?: string;
  server?: string;
  data?: string;
  error?: string;
  // exec.open carries the shell command (and optional cwd); exec.exit carries
  // the process exit code.
  command?: string;
  cwd?: string;
  code?: number;
  // server.remove carries the key of the server to drop from local config.
  key?: string;
  // Consumer pod id from mcp.open, echoed on every up-frame so the owning pod
  // routes replies. Explicitly `| undefined` (not just optional) because call
  // sites forward `frame.pod` verbatim, which is itself `string | undefined`.
  pod?: string | undefined;
}

export class Tunnel {
  private ws: WebSocket | null = null;
  private sessions = new Map<string, ServerSession>();
  private reconnectDelay = RECONNECT_MIN_MS;
  private stopped = false;

  constructor(private creds: Credentials) {}

  async run(): Promise<void> {
    while (!this.stopped) {
      try {
        await this.connectOnce();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          // A definitive auth failure (revoked or unpaired) will never recover
          // on retry — exit instead of reconnect-looping forever.
          bridgeLogger().error(
            "[gaia bridge] this device is no longer authorized (revoked or unpaired). Re-pair with: gaia bridge login",
          );
          this.stopped = true;
        } else {
          bridgeLogger().error(
            `[gaia bridge] connection error: ${e instanceof Error ? e.message : e}`,
          );
        }
      }
      if (this.stopped) break;
      await this.backoff();
    }
  }

  async stop(): Promise<void> {
    this.stopped = true;
    // Close sessions first so spawned local MCP child processes are terminated
    // (transport.close()), then drop the socket. On a signal-driven shutdown the
    // caller can await this before process.exit so nothing is orphaned.
    await this.closeAllSessions();
    this.ws?.close();
  }

  private async connectOnce(): Promise<void> {
    // Rotation is an interprocess-mutexed triple (load → exchange → save): a
    // concurrent `gaia bridge add` in another process must not exchange the
    // same refresh token, or the loser trips reuse-detection and revokes us.
    const { creds, accessToken } = await rotateCredentials();
    this.creds = creds;

    const wsUrl = `${this.creds.apiUrl.replace(/^http/, "ws")}/api/v1/ws/device`;
    const ws = new WebSocket(wsUrl, {
      headers: { authorization: `Bearer ${accessToken}` },
    });
    this.ws = ws;

    // Stays pending for the connection's whole life: settles only when the
    // socket CLOSES (resolve → reconnect) or fails before opening (reject).
    // Resolving on `open` would return immediately and spin run() in a tight loop.
    await new Promise<void>((resolvePromise, rejectPromise) => {
      let opened = false;
      let settled = false;
      const settle = (finish: () => void) => {
        if (!settled) {
          settled = true;
          finish();
        }
      };

      ws.on("open", () => {
        opened = true;
        // Decorrelate the next reconnect across the fleet, not RECONNECT_MIN_MS.
        this.reconnectDelay = RECONNECT_SPREAD_MS;
        const serverKeys = loadConfig().servers.map((s) => s.key);
        this.send({ t: FRAME.HELLO, servers: serverKeys });
        bridgeLogger().info(
          `[gaia bridge] connected — exposing: ${serverKeys.join(", ") || "(nothing configured)"}`,
        );
      });

      ws.on("message", (raw: WebSocket.RawData) => {
        this.guardRejection(
          this.onFrame(raw.toString()),
          "frame handler error",
        );
      });

      ws.on("close", () => {
        this.guardRejection(this.closeAllSessions(), "session cleanup error");
        this.ws = null;
        settle(() =>
          opened
            ? resolvePromise()
            : rejectPromise(new Error("socket closed before open")),
        );
      });

      ws.on("error", (err: Error) => {
        // A post-open error is followed by `close`, which resolves; only a
        // pre-open error needs to reject here.
        if (!opened) settle(() => rejectPromise(err));
      });
    });
  }

  private async onFrame(raw: string): Promise<void> {
    let frame: Frame;
    try {
      frame = JSON.parse(raw) as Frame;
    } catch {
      return;
    }

    switch (frame.t) {
      case FRAME.PING:
        this.send({ t: FRAME.PONG });
        return;
      case FRAME.MCP_OPEN:
        await this.openSession(frame);
        return;
      case FRAME.MCP_MSG:
        await this.forwardToServer(frame);
        return;
      case FRAME.MCP_CLOSE:
        await this.closeSession(frame.sid);
        return;
      case FRAME.EXEC_OPEN:
        await this.runExec(frame);
        return;
      case FRAME.REVOKE:
        bridgeLogger().error(
          "[gaia bridge] this device was revoked — exiting.",
        );
        await this.stop();
        return;
      case FRAME.SERVER_REMOVE:
        // The server was deleted from the GAIA UI; drop it from local config so
        // it isn't re-registered on the next reconnect.
        if (frame.key && removeServer(frame.key)) {
          bridgeLogger().info(
            `[gaia bridge] removed server '${frame.key}' (deleted in GAIA).`,
          );
        }
        return;
      default:
        return;
    }
  }

  private async openSession(frame: Frame): Promise<void> {
    const sid = frame.sid;
    const serverKey = frame.server;
    // Echo the consumer pod id on every reply for this session so the cloud
    // routes them to the pod that opened it.
    const pod = frame.pod;
    if (!sid || !serverKey) return;

    const config = loadConfig().servers.find((s) => s.key === serverKey);
    if (!config) {
      this.send({
        t: FRAME.MCP_ERROR,
        sid,
        pod,
        error: `Unknown server '${serverKey}'`,
      });
      return;
    }

    // The cloud's /mcp/test request blocks on this spawn, so a slow or failing
    // local server looks like a hung tunnel from the other side — log what we're
    // doing and how long it took, or the only evidence is the caller's timeout.
    const startedAt = Date.now();
    bridgeLogger().info(
      `[gaia bridge] opening MCP session for '${serverKey}'…`,
    );
    try {
      const session = await openServerSession(config);
      // Frames from the local server → up the tunnel.
      session.transport.onmessage = (message: JSONRPCMessage) => {
        this.send({
          t: FRAME.MCP_MSG,
          sid,
          pod,
          data: JSON.stringify(message),
        });
      };
      session.transport.onclose = () => {
        // closeSession() removes the session from the map before closing the
        // transport, so a still-registered session here means the local server
        // exited on its own. Tell the cloud so its call fails fast, not on timeout.
        if (this.sessions.has(sid)) {
          this.send({
            t: FRAME.MCP_ERROR,
            sid,
            pod,
            error: `Local server '${serverKey}' exited`,
          });
        }
        this.guardRejection(this.closeSession(sid), "session close error");
      };
      await session.transport.start();
      this.sessions.set(sid, session);
      this.send({ t: FRAME.MCP_OPENED, sid, pod });
      bridgeLogger().info(
        `[gaia bridge] MCP session for '${serverKey}' ready in ${Date.now() - startedAt}ms`,
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      bridgeLogger().error(
        `[gaia bridge] MCP session for '${serverKey}' failed after ${Date.now() - startedAt}ms: ${message}`,
      );
      this.send({ t: FRAME.MCP_ERROR, sid, pod, error: message });
    }
  }

  private async forwardToServer(frame: Frame): Promise<void> {
    const session = frame.sid ? this.sessions.get(frame.sid) : undefined;
    if (!session || !frame.data) return;
    try {
      const message = JSON.parse(frame.data) as JSONRPCMessage;
      await session.transport.send(message);
    } catch (e) {
      bridgeLogger().error(
        `[gaia bridge] forward error: ${e instanceof Error ? e.message : e}`,
      );
    }
  }

  private async runExec(frame: Frame): Promise<void> {
    const sid = frame.sid;
    const pod = frame.pod;
    const command = frame.command;
    if (!sid || !command) return;
    // Echo the consumer pod on every up-frame so the cloud routes the stream to
    // the pod that opened the session (same contract as the MCP path).
    await runDeviceExec(command, frame.cwd, {
      stdout: (data) => this.send({ t: FRAME.EXEC_STDOUT, sid, pod, data }),
      stderr: (data) => this.send({ t: FRAME.EXEC_STDERR, sid, pod, data }),
      exit: (code) => this.send({ t: FRAME.EXEC_EXIT, sid, pod, code }),
    });
  }

  private async closeSession(sid: string | undefined): Promise<void> {
    if (!sid) return;
    const session = this.sessions.get(sid);
    if (!session) return;
    this.sessions.delete(sid);
    try {
      await session.close();
    } catch {
      // best-effort teardown
    }
  }

  private async closeAllSessions(): Promise<void> {
    const sids = [...this.sessions.keys()];
    await Promise.all(sids.map((sid) => this.closeSession(sid)));
  }

  private send(frame: Frame & Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(frame));
    }
  }

  /** Rejection boundary for fire-and-forget promises. Without it a rejection
   * becomes an unhandled rejection — silently lost in the CLI, and a popped
   * error dialog in Electron's main process when the desktop app hosts the
   * bridge. Route it to the logger instead. */
  private guardRejection(promise: Promise<void>, context: string): void {
    promise.catch((e) => {
      bridgeLogger().error(
        `[gaia bridge] ${context}: ${e instanceof Error ? e.message : e}`,
      );
    });
  }

  private async backoff(): Promise<void> {
    // Exponential with full jitter. randomInt (CSPRNG) rather than Math.random():
    // the jitter is not security-sensitive, but this runs at most once per
    // reconnect, so there is no cost to avoiding a weak PRNG.
    const jittered = randomInt(this.reconnectDelay);
    bridgeLogger().info(`[gaia bridge] reconnecting in ${jittered}ms…`);
    await new Promise((r) => setTimeout(r, jittered));
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, RECONNECT_MAX_MS);
  }
}
