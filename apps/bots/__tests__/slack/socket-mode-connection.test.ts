/**
 * The Slack connection gauge, driven over a real socket.
 *
 * Real: SlackAdapter, Bolt, the Socket Mode client, the bot registry. Faked: Slack
 * itself (its Web API over HTTP and its Socket Mode WebSocket) and the GAIA API.
 */

import { once } from "node:events";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { type WebSocket, WebSocketServer } from "ws";
import { botRegistry } from "../../../../libs/shared/ts/src/bots/metrics";
import { SlackAdapter } from "../../slack/src/adapter";

const CONNECTED_GAUGE = "gaia_bot_platform_connected";
// @slack/socket-mode waits its clientPingTimeout default before the first reconnect.
const RECONNECT_DELAY_MS = 5_000;

let slack: Server;
let sockets: WebSocketServer;
let slackUrl: string;

function listen(server: Server): Promise<number> {
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () =>
      resolve((server.address() as AddressInfo).port),
    );
  });
}

async function freePort(): Promise<number> {
  const probe = createServer();
  const port = await listen(probe);
  await new Promise((resolve) => probe.close(resolve));
  return port;
}

async function nextSocket(): Promise<WebSocket> {
  const [socket] = (await once(sockets, "connection")) as [WebSocket];
  return socket;
}

async function slackConnected(): Promise<number | undefined> {
  const gauge = await botRegistry.getSingleMetric(CONNECTED_GAUGE)?.get();
  return gauge?.values.find((sample) => sample.labels.platform === "slack")
    ?.value;
}

beforeAll(async () => {
  slack = createServer((request, response) => {
    const answers: Record<string, unknown> = {
      "/api/apps.connections.open": {
        ok: true,
        url: slackUrl.replace("http", "ws"),
      },
      "/api/auth.test": {
        ok: true,
        user_id: "U1",
        bot_id: "B1",
        team_id: "T1",
      },
      "/api/v1/bot/conversations/active": [],
    };
    const answer = answers[new URL(request.url ?? "", slackUrl).pathname];
    response.writeHead(answer === undefined ? 404 : 200, {
      "Content-Type": "application/json",
    });
    response.end(JSON.stringify(answer ?? { ok: false, error: "unknown" }));
  });
  slackUrl = `http://127.0.0.1:${await listen(slack)}`;
  sockets = new WebSocketServer({ server: slack });
  sockets.on("connection", (socket) =>
    socket.send(JSON.stringify({ type: "hello" })),
  );

  vi.stubEnv("ENV", "selfhost");
  vi.stubEnv("SLACK_BOT_TOKEN", "xoxb-test");
  vi.stubEnv("SLACK_SIGNING_SECRET", "signing-secret");
  vi.stubEnv("SLACK_APP_TOKEN", "xapp-test");
  vi.stubEnv("GAIA_API_URL", slackUrl);
  vi.stubEnv("GAIA_BOT_API_KEY", "bot-key");
  vi.stubEnv("FRONTEND_URL", "http://127.0.0.1");
  vi.stubEnv("BOT_LOG_HASH_SECRET", "0".repeat(64));
  vi.stubEnv("BOT_SERVER_PORT", String(await freePort()));
  vi.stubEnv("RABBITMQ_URL", "");
  vi.stubEnv("POSTHOG_PROJECT_TOKEN", "");
});

afterAll(async () => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  for (const socket of sockets.clients) socket.terminate();
  await new Promise((resolve) => sockets.close(resolve));
  await new Promise((resolve) => slack.close(resolve));
});

describe("SlackAdapter connection gauge over Socket Mode", () => {
  it("follows the socket through connect, a dropped socket, reconnect and shutdown", async () => {
    class LocalSlackAdapter extends SlackAdapter {
      protected override readonly slackApiUrl = `${slackUrl}/api/`;
    }
    const adapter = new LocalSlackAdapter();

    const firstSocket = nextSocket();
    await adapter.boot([]);
    expect(await slackConnected()).toBe(1);

    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const secondSocket = nextSocket();
    (await firstSocket).close();
    await vi.waitFor(async () => expect(await slackConnected()).toBe(0));

    await vi.advanceTimersByTimeAsync(RECONNECT_DELAY_MS);
    await secondSocket;
    await vi.waitFor(async () => expect(await slackConnected()).toBe(1));
    vi.useRealTimers();

    // Bolt's receiver.stop() resolves before the close handshake finishes.
    await adapter.shutdown("test");
    await vi.waitFor(async () => expect(await slackConnected()).toBe(0));
  });
});
