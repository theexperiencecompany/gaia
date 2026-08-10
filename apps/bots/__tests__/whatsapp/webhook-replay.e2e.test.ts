/**
 * In-process replay test for the real WhatsApp Hono webhook.
 *
 * Synthetic Kapso payloads (no real PII) are HMAC-SHA256 signed with the same
 * scheme the production webhook verifies, then POSTed at the REAL webhook route
 * mounted by `WhatsAppAdapter.registerEvents()` — running the actual signature
 * check, batch handling, replay-window guard, and dispatch. Only the platform
 * SDK (Kapso) and the GaiaClient network boundary are faked; no live API.
 *
 * Covered:
 * 1. a valid signed text message dispatches a chat turn with the right waId/text
 * 2. a bad signature is rejected (401) and nothing dispatches
 * 3. a batched delivery dispatches every event
 * 4. an image message routes through the shared media pipeline
 */

import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { Hono } from "hono";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@kapso/whatsapp-cloud-api", () => ({
  WhatsAppClient: vi.fn(() => ({})),
}));

import { WhatsAppAdapter } from "../../whatsapp/src/adapter";

const SECRET = "conformance-webhook-secret-0123456789abcdef";

interface KapsoEvent {
  message: {
    id: string;
    timestamp: string;
    type: string;
    [k: string]: unknown;
  };
  conversation: { phone_number: string; [k: string]: unknown };
  [k: string]: unknown;
}

function loadFixture(name: string): KapsoEvent {
  const path = fileURLToPath(
    new URL(`../fixtures/kapso/${name}`, import.meta.url),
  );
  return JSON.parse(readFileSync(path, "utf8")) as KapsoEvent;
}

/** Stamps a fresh timestamp so the event is inside the replay window. */
function freshen(event: KapsoEvent): KapsoEvent {
  event.message.timestamp = String(Math.floor(Date.now() / 1000));
  return event;
}

function sign(body: string): string {
  return createHmac("sha256", SECRET).update(body, "utf8").digest("hex");
}

interface Harnessed {
  app: Hono;
  gaia: {
    chatStream: ReturnType<typeof vi.fn>;
    checkAuthStatus: ReturnType<typeof vi.fn>;
    createLinkToken: ReturnType<typeof vi.fn>;
    getPricingUrl: () => string;
  };
  waClient: {
    messages: {
      markRead: ReturnType<typeof vi.fn>;
      sendText: ReturnType<typeof vi.fn>;
    };
  };
  adapter: WhatsAppAdapter;
}

async function buildHarness(): Promise<Harnessed> {
  const adapter = new WhatsAppAdapter();
  const gaia = {
    chatStream: vi.fn(
      async (
        _req: unknown,
        _onChunk: unknown,
        onDone: (full: string, conv: string) => Promise<void>,
      ) => {
        await onDone("ok", "conv-1");
        return "conv-1";
      },
    ),
    // Authenticated → the welcome path is skipped and the user is cached.
    checkAuthStatus: vi.fn(async () => ({
      authenticated: true,
      platform: "whatsapp",
      platformUserId: "",
    })),
    createLinkToken: vi.fn(async () => ({ token: "t", authUrl: "u" })),
    getPricingUrl: () => "https://gaia.test/pricing",
  };
  const waClient = {
    messages: {
      markRead: vi.fn(async () => ({})),
      sendText: vi.fn(async () => ({ messages: [{ id: "wamid.out" }] })),
    },
  };
  (adapter as unknown as { gaia: unknown }).gaia = gaia;
  (adapter as unknown as { waConfig: unknown }).waConfig = {
    kapsoApiKey: "k",
    kapsoPhoneNumberId: "pn",
    kapsoWebhookSecret: SECRET,
  };
  (adapter as unknown as { waClient: unknown }).waClient = waClient;

  const app = new Hono();
  (adapter as unknown as { _botServer: unknown })._botServer = { app };
  await (
    adapter as unknown as { registerEvents: () => Promise<void> }
  ).registerEvents();

  return { app, gaia, waClient, adapter };
}

function post(
  app: Hono,
  body: string,
  headers: Record<string, string>,
): Promise<Response> {
  return app.request("/webhook", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-webhook-event": "whatsapp.message.received",
      ...headers,
    },
    body,
  });
}

describe("WhatsApp webhook replay (real Hono webhook, in-process)", () => {
  let h: Harnessed;

  beforeEach(async () => {
    vi.clearAllMocks();
    h = await buildHarness();
  });

  it("dispatches a chat turn for a valid signed text message", async () => {
    const body = JSON.stringify(freshen(loadFixture("text-message.json")));
    const res = await post(h.app, body, { "x-webhook-signature": sign(body) });

    expect(res.status).toBe(200);
    await vi.waitFor(() => expect(h.gaia.chatStream).toHaveBeenCalled());

    const request = h.gaia.chatStream.mock.calls[0][0] as {
      message: string;
      platform: string;
      platformUserId: string;
    };
    expect(request.platform).toBe("whatsapp");
    // wa_id is the phone number without the leading "+".
    expect(request.platformUserId).toBe("15550000001");
    expect(request.message).toBe("remind me to water the plants tomorrow");
  });

  it("rejects a tampered signature with 401 and dispatches nothing", async () => {
    const body = JSON.stringify(freshen(loadFixture("text-message.json")));
    const res = await post(h.app, body, {
      "x-webhook-signature": sign(`${body} `), // signed a different body
    });

    expect(res.status).toBe(401);
    await new Promise((r) => setTimeout(r, 20));
    expect(h.gaia.chatStream).not.toHaveBeenCalled();
  });

  it("dispatches every event in a batched delivery", async () => {
    const a = freshen(loadFixture("text-message.json"));
    const b = freshen(loadFixture("text-message.json"));
    b.message.id = "wamid.SYNTHETIC0001b";
    b.conversation.phone_number = "+15550000009";

    const batch = {
      type: "whatsapp.message.received",
      batch: true,
      data: [a, b],
      batch_info: {
        size: 2,
        window_ms: 1000,
        first_sequence: 1,
        last_sequence: 2,
        conversation_id: "conv_synthetic_1",
      },
    };
    const body = JSON.stringify(batch);
    const res = await post(h.app, body, {
      "x-webhook-signature": sign(body),
      "x-webhook-batch": "true",
    });

    expect(res.status).toBe(200);
    await vi.waitFor(() => expect(h.gaia.chatStream).toHaveBeenCalledTimes(2));
  });

  it("routes an image message through the shared media pipeline", async () => {
    // Short-circuit the media decision so no real download/upload runs; we only
    // assert the webhook extracted the media and routed it to resolveIncomingMedia.
    const resolveIncomingMedia = vi.fn(async () => ({
      action: "reply" as const,
      text: "I see your image.",
    }));
    (
      h.adapter as unknown as { resolveIncomingMedia: unknown }
    ).resolveIncomingMedia = resolveIncomingMedia;

    const body = JSON.stringify(freshen(loadFixture("image-message.json")));
    const res = await post(h.app, body, { "x-webhook-signature": sign(body) });

    expect(res.status).toBe(200);
    await vi.waitFor(() => expect(resolveIncomingMedia).toHaveBeenCalled());
    expect(resolveIncomingMedia.mock.calls[0][0]).toMatchObject({
      kind: "image",
      caption: "what is in this picture?",
    });
    await vi.waitFor(() =>
      expect(h.waClient.messages.sendText).toHaveBeenCalledWith(
        expect.objectContaining({ body: "I see your image." }),
      ),
    );
  });
});
