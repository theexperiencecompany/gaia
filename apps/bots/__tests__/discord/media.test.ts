/**
 * Tests for Discord inbound-media mapping and the capped attachment download.
 *
 * `extractDiscordMedia` is a pure mapping from a discord.js Message onto the
 * shared `IncomingMedia` shape — including the declared `size`, which lets the
 * shared pipeline reject an oversize attachment before any download happens.
 * `downloadDiscordAttachment` must stop reading at the cap it is handed rather
 * than buffering an untrusted CDN payload whole.
 */

import type { Message } from "discord.js";
import { MessageFlags } from "discord.js";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  downloadDiscordAttachment,
  extractDiscordMedia,
} from "../../discord/src/media";

const CHUNK = 256;
const CAP = 1000;

interface FakeAttachment {
  url?: string;
  name?: string;
  contentType?: string | null;
  size?: number;
}

function makeMessage(overrides: {
  attachment?: FakeAttachment | null;
  attachments?: FakeAttachment[];
  stickers?: number;
  voice?: boolean;
}): Message {
  const { attachment = null, stickers = 0, voice = false } = overrides;
  const list = (overrides.attachments ?? (attachment ? [attachment] : [])).map(
    (a) => ({
      url: a.url ?? "https://cdn.discord.test/photo.jpg",
      name: a.name ?? "photo.jpg",
      contentType: a.contentType === undefined ? "image/jpeg" : a.contentType,
      size: a.size ?? 4096,
    }),
  );
  return {
    // discord.js hands attachments as a Collection (a Map keyed by id).
    attachments: new Map(list.map((a, i) => [`att-${i}`, a])),
    stickers: { size: stickers },
    flags: {
      has: (flag: bigint | number) =>
        voice && flag === MessageFlags.IsVoiceMessage,
    },
  } as unknown as Message;
}

function endlessBody(): {
  body: ReadableStream<Uint8Array>;
  produced: () => number;
  cancelled: () => boolean;
} {
  let produced = 0;
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      produced += CHUNK;
      controller.enqueue(new Uint8Array(CHUNK).fill(3));
    },
    cancel() {
      cancelled = true;
    },
  });
  return { body, produced: () => produced, cancelled: () => cancelled };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("extractDiscordMedia", () => {
  it("maps the attachment's declared size onto sizeBytes", () => {
    const extracted = extractDiscordMedia(
      makeMessage({ attachment: { size: 12_345_678 } }),
    );

    expect(extracted[0]?.media).toMatchObject({
      kind: "image",
      mimeType: "image/jpeg",
      sizeBytes: 12_345_678,
    });
  });

  it("keeps the document filename alongside the declared size", () => {
    const extracted = extractDiscordMedia(
      makeMessage({
        attachment: {
          name: "report.pdf",
          contentType: "application/pdf",
          size: 2048,
        },
      }),
    );

    expect(extracted[0]?.media).toMatchObject({
      kind: "document",
      filename: "report.pdf",
      sizeBytes: 2048,
    });
  });

  it("flags a voice message and still reports its size", () => {
    const extracted = extractDiscordMedia(
      makeMessage({
        attachment: { contentType: "audio/ogg", size: 900 },
        voice: true,
      }),
    );

    expect(extracted[0]?.media).toMatchObject({
      kind: "audio",
      isVoiceNote: true,
      sizeBytes: 900,
    });
  });

  it("returns a sticker with no size because it is never downloaded", () => {
    const extracted = extractDiscordMedia(makeMessage({ stickers: 1 }));

    expect(extracted).toHaveLength(1);
    expect(extracted[0]?.url).toBe("");
    expect(extracted[0]?.media.kind).toBe("sticker");
    expect(extracted[0]?.media.sizeBytes).toBeUndefined();
  });

  it("returns nothing when the message carries no media", () => {
    expect(extractDiscordMedia(makeMessage({}))).toEqual([]);
  });

  it("returns every attachment in the message, not just the first", () => {
    const extracted = extractDiscordMedia(
      makeMessage({
        attachments: [
          { url: "https://cdn.discord.test/1.png", contentType: "image/png" },
          { url: "https://cdn.discord.test/2.png", contentType: "image/png" },
          {
            url: "https://cdn.discord.test/notes.pdf",
            name: "notes.pdf",
            contentType: "application/pdf",
          },
        ],
      }),
    );

    expect(extracted.map((e) => e.url)).toEqual([
      "https://cdn.discord.test/1.png",
      "https://cdn.discord.test/2.png",
      "https://cdn.discord.test/notes.pdf",
    ]);
    expect(extracted[2]?.media).toMatchObject({
      kind: "document",
      filename: "notes.pdf",
    });
  });
});

describe("downloadDiscordAttachment", () => {
  it("stops at the cap and cancels the CDN stream instead of buffering it whole", async () => {
    const { body, produced, cancelled } = endlessBody();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, body })),
    );

    const bytes = await downloadDiscordAttachment(
      "https://cdn.discord.test/huge.bin",
      CAP,
    );

    expect(bytes.byteLength).toBe(CAP);
    expect(cancelled()).toBe(true);
    expect(produced()).toBeLessThanOrEqual(CAP + 2 * CHUNK);
  });

  it("aborts the request after the download timeout", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      body: new ReadableStream<Uint8Array>({
        start(controller) {
          controller.close();
        },
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    await downloadDiscordAttachment("https://cdn.discord.test/a.bin", CAP);

    expect(fetchMock.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
  });

  it("throws an error carrying the HTTP status when the CDN rejects the fetch", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 404, body: null })),
    );

    await expect(
      downloadDiscordAttachment("https://cdn.discord.test/gone.bin", CAP),
    ).rejects.toMatchObject({ status: 404 });
  });
});
