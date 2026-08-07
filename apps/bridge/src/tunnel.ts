// The outbound tunnel: one WebSocket from this machine to GAIA, over which the
// cloud opens MCP sessions to our local servers and relays JSON-RPC frames. No
// inbound ports. Reconnects with jittered backoff; refreshes the connect token
// each dial (and rotates the stored refresh credential).

import { randomInt } from "node:crypto";
import type { JSONRPCMessage } from "@modelcontextprotocol/sdk/types.js";
import WebSocket from "ws";
import { ApiError, exchangeToken } from "./api.js";
import { loadConfig, saveCredentials } from "./config.js";
import type { Credentials } from "./config.types.js";
import {
  FRAME,
  RECONNECT_MAX_MS,
  RECONNECT_MIN_MS,
  RECONNECT_SPREAD_MS,
} from "./constants.js";
import { openServerSession, type ServerSession } from "./servers.js";

interface Frame {
  t: string;
  sid?: string;
  server?: string;
  data?: string;
  error?: string;
  // Consumer pod id from mcp.open; echoed on every up-frame so the owning pod
  // routes replies to the pod running the session. Explicitly `| undefined`
  // (not just optional) because call sites forward `frame.pod` verbatim,
  // which is itself `string | undefined`.
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
          console.error(
            "[gaia bridge] this device is no longer authorized (revoked or unpaired). Re-pair with: gaia bridge login",
          );
          this.stopped = true;
        } else {
          console.error(
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
    const token = await exchangeToken(
      this.creds.apiUrl,
      this.creds.refreshToken,
    );
    // Persist the rotated refresh credential immediately — the old one is dead.
    this.creds = { ...this.creds, refreshToken: token.refresh_token };
    saveCredentials(this.creds);

    const wsUrl = `${this.creds.apiUrl.replace(/^http/, "ws")}/api/v1/ws/device`;
    const ws = new WebSocket(wsUrl, {
      headers: { authorization: `Bearer ${token.access_token}` },
    });
    this.ws = ws;

    // This promise stays pending for the whole life of the connection: it
    // settles only when the socket CLOSES (resolve → reconnect) or fails before
    // ever opening (reject). Resolving on `open` would make connectOnce() return
    // immediately and run() spin up a new socket in a tight loop — the tunnel
    // would never be held.
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
        console.error(
          `[gaia bridge] connected — exposing: ${serverKeys.join(", ") || "(nothing configured)"}`,
        );
      });

      ws.on("message", (raw: WebSocket.RawData) => {
        void this.onFrame(raw.toString());
      });

      ws.on("close", () => {
        void this.closeAllSessions();
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
      case FRAME.REVOKE:
        console.error("[gaia bridge] this device was revoked — exiting.");
        await this.stop();
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
        // exited on its own. Tell the cloud so its call fails immediately
        // instead of hanging until the read timeout; an intentional close
        // (already removed) skips this.
        if (this.sessions.has(sid)) {
          this.send({
            t: FRAME.MCP_ERROR,
            sid,
            pod,
            error: `Local server '${serverKey}' exited`,
          });
        }
        void this.closeSession(sid);
      };
      await session.transport.start();
      this.sessions.set(sid, session);
      this.send({ t: FRAME.MCP_OPENED, sid, pod });
    } catch (e) {
      this.send({
        t: FRAME.MCP_ERROR,
        sid,
        pod,
        error: e instanceof Error ? e.message : String(e),
      });
    }
  }

  private async forwardToServer(frame: Frame): Promise<void> {
    const session = frame.sid ? this.sessions.get(frame.sid) : undefined;
    if (!session || !frame.data) return;
    try {
      const message = JSON.parse(frame.data) as JSONRPCMessage;
      await session.transport.send(message);
    } catch (e) {
      console.error(
        `[gaia bridge] forward error: ${e instanceof Error ? e.message : e}`,
      );
    }
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

  private async backoff(): Promise<void> {
    // Exponential with full jitter. randomInt (CSPRNG) rather than Math.random():
    // the jitter is not security-sensitive, but this runs at most once per
    // reconnect, so there is no cost to avoiding a weak PRNG.
    const jittered = randomInt(this.reconnectDelay);
    console.error(`[gaia bridge] reconnecting in ${jittered}ms…`);
    await new Promise((r) => setTimeout(r, jittered));
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, RECONNECT_MAX_MS);
  }
}
