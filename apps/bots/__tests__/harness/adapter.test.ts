/**
 * Unit tests for the HarnessAdapter in isolation.
 *
 * These use the REAL @gaia/shared (aliased to source by vitest.config.ts) — only
 * the GaiaClient's network boundary (`chatStream` / `createLinkToken`) is faked.
 * So the real streaming pipeline, markdown converters, splitting, and limits all
 * run; the tests assert the transcript the harness records.
 *
 * Covered:
 * 1. plain reply → one send bubble, rendered by the emulated platform's converter
 * 2. markdown fidelity → WhatsApp `**bold**` becomes `*bold*` (real converter)
 * 3. long reply → split into multiple bubbles, each within the platform limit
 * 4. auth prompt → the rendered "link your account" message is delivered
 * 5. plan gate → the rendered upgrade prompt with the pricing URL is delivered
 * 6. edit support → Telegram edits in place; WhatsApp only ever sends
 * 7. outbound delivery → deliverOutbound records an outbound-delivery event
 * 8. command path → an ephemeral reply records an ephemeral event
 */

import type { PlatformName } from "@gaia/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HarnessAdapter } from "../../harness/src/adapter";
import { resolveEmulation } from "../../harness/src/emulation";
import { TranscriptRecorder } from "../../harness/src/transcript";
import type { TranscriptEvent } from "../../harness/src/transcript.types";

/** A scripted stand-in for the GaiaClient streaming/network boundary. */
interface StreamScript {
  chunks?: string[];
  /** When set, the stream fails with this error instead of streaming chunks. */
  error?: string;
  authUrl?: string;
  /**
   * When true, yields a macrotask between chunks so the shared streamer's
   * throttled edit queue flushes — required to observe mid-stream in-place
   * edits on streaming platforms (otherwise all chunks collapse into one final
   * delivery).
   */
  liveEdits?: boolean;
}

const tick = (): Promise<void> => new Promise((r) => setTimeout(r, 0));

function makeGaia(script: StreamScript) {
  return {
    chatStream: vi.fn(
      async (
        _req: unknown,
        onChunk: (t: string) => void | Promise<void>,
        onDone: (full: string, conv: string) => void | Promise<void>,
        onError: (e: Error) => void | Promise<void>,
      ) => {
        if (script.error) {
          await onError(new Error(script.error));
          return "";
        }
        const chunks = script.chunks ?? [];
        for (const chunk of chunks) {
          await onChunk(chunk);
          if (script.liveEdits) await tick();
        }
        await onDone(chunks.join(""), "conv-1");
        return "conv-1";
      },
    ),
    createLinkToken: vi.fn(async () => ({
      token: "tok",
      authUrl: script.authUrl ?? "https://gaia.test/auth?token=abc123",
    })),
    getPricingUrl: () => "https://gaia.test/pricing",
  };
}

/** Builds a harness adapter for `platform` with a scripted gaia injected. */
function makeAdapter(
  platform: PlatformName,
  script: StreamScript,
): { adapter: HarnessAdapter; recorder: TranscriptRecorder } {
  const recorder = new TranscriptRecorder(platform);
  const adapter = new HarnessAdapter(resolveEmulation(platform), recorder);
  (adapter as unknown as { gaia: ReturnType<typeof makeGaia> }).gaia =
    makeGaia(script);
  return { adapter, recorder };
}

/** Convenience: drive one message and return the recorded events. */
async function drive(
  platform: PlatformName,
  script: StreamScript,
  message: string,
): Promise<readonly TranscriptEvent[]> {
  const { adapter, recorder } = makeAdapter(platform, script);
  await adapter.simulateMessage("dev-user-1", message);
  return recorder.getEvents();
}

const sends = (events: readonly TranscriptEvent[]) =>
  events.filter((e) => e.type === "send");
const texts = (events: readonly TranscriptEvent[]) =>
  events.flatMap((e) => ("text" in e ? [e.text] : []));

describe("HarnessAdapter — plain reply", () => {
  it("records inbound, typing, and a single send bubble", async () => {
    const events = await drive(
      "telegram",
      { chunks: ["Hello world"] },
      "hi there",
    );
    const types = events.map((e) => e.type);
    expect(types).toContain("inbound");
    expect(types).toContain("typing");
    expect(sends(events)).toHaveLength(1);
    expect(sends(events)[0]).toMatchObject({ text: "Hello world" });
  });
});

describe("HarnessAdapter — markdown fidelity via the real converter", () => {
  it("renders WhatsApp bold with the platform's real converter", async () => {
    const events = await drive("whatsapp", { chunks: ["**Bold** move"] }, "hi");
    // convertToWhatsAppMarkdown turns **bold** into *bold* — proving the harness
    // uses the emulated platform's real converter, not a re-hardcoded one.
    expect(sends(events)[0]).toMatchObject({ text: "*Bold* move" });
  });

  it("renders Telegram HTML with the platform's real converter", async () => {
    const events = await drive("telegram", { chunks: ["**Bold** move"] }, "hi");
    expect(sends(events)[0]).toMatchObject({ text: "<b>Bold</b> move" });
  });
});

describe("HarnessAdapter — long reply splitting", () => {
  it("splits a reply over the Telegram limit into multiple in-limit bubbles", async () => {
    // ~9000 chars of words → chunkResponse splits at the 4096 limit.
    const long = Array.from({ length: 1500 }, (_, i) => `word${i}`).join(" ");
    const events = await drive("telegram", { chunks: [long] }, "tell me lots");

    const sendEvents = sends(events);
    expect(sendEvents.length).toBeGreaterThan(1);
    for (const send of sendEvents) {
      expect(send.length).toBeLessThanOrEqual(4096);
    }
    const split = events.find((e) => e.type === "split");
    expect(split).toBeDefined();
    expect(split).toMatchObject({
      segmentCount: sendEvents.length,
      limit: 4096,
    });
  });
});

describe("HarnessAdapter — auth prompt", () => {
  it("delivers the rendered auth-link message on not_authenticated", async () => {
    const events = await drive(
      "telegram",
      { error: "not_authenticated", authUrl: "https://gaia.test/auth?t=xyz" },
      "do something",
    );
    const delivered = texts(events).join("\n");
    expect(delivered).toContain("https://gaia.test/auth?t=xyz");
    expect(delivered).toContain("Link your account");
  });
});

describe("HarnessAdapter — plan gate", () => {
  it("delivers the rendered upgrade prompt on plan_required", async () => {
    const events = await drive(
      "telegram",
      { error: "plan_required" },
      "do something",
    );
    const delivered = texts(events).join("\n");
    expect(delivered).toContain("https://gaia.test/pricing");
    expect(delivered).toContain("Pro");
  });
});

describe("HarnessAdapter — edit semantics", () => {
  it("Telegram edits a bubble in place (supportsEdit = true)", async () => {
    // Two chunks that fit one bubble: the first streams (send), the final
    // delivery edits it in place.
    const events = await drive(
      "telegram",
      { chunks: ["Hello ", "world"], liveEdits: true },
      "hi",
    );
    expect(events.some((e) => e.type === "edit")).toBe(true);
    expect(sends(events)).toHaveLength(1);
  });

  it("WhatsApp never edits — every update is a new send (supportsEdit = false)", async () => {
    const events = await drive(
      "whatsapp",
      { chunks: ["Hello ", "world"] },
      "hi",
    );
    expect(events.some((e) => e.type === "edit")).toBe(false);
    expect(sends(events).length).toBeGreaterThanOrEqual(1);
  });
});

describe("HarnessAdapter — outbound delivery", () => {
  it("records an outbound-delivery event from deliverOutbound", async () => {
    const recorder = new TranscriptRecorder("telegram");
    const adapter = new HarnessAdapter(resolveEmulation("telegram"), recorder);
    await (
      adapter as unknown as {
        deliverOutbound: (id: string, text: string) => Promise<void>;
      }
    ).deliverOutbound("dev-telegram-42", "Your reminder is due");

    expect(recorder.getEvents()).toEqual([
      expect.objectContaining({
        type: "outbound-delivery",
        destinationId: "dev-telegram-42",
        text: "Your reminder is due",
      }),
    ]);
  });
});

describe("HarnessAdapter — command path", () => {
  let recorder: TranscriptRecorder;
  let adapter: HarnessAdapter;

  beforeEach(() => {
    recorder = new TranscriptRecorder("telegram");
    adapter = new HarnessAdapter(resolveEmulation("telegram"), recorder);
    (adapter as unknown as { gaia: ReturnType<typeof makeGaia> }).gaia =
      makeGaia({ chunks: [] });
  });

  it("routes an unknown /command through dispatch and records an ephemeral", async () => {
    // The base dispatchCommand sends "Unknown command" via sendEphemeral when no
    // command is registered — proving the command path reaches the harness target.
    await adapter.simulateMessage("dev-user-1", "/nope");
    const ephemeral = recorder.getEvents().find((e) => e.type === "ephemeral");
    expect(ephemeral).toBeDefined();
    expect(ephemeral).toMatchObject({ text: expect.stringContaining("nope") });
  });
});
