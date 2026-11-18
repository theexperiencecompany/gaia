/**
 * Adapter-level tests for the Discord inbound-media pipeline.
 *
 * These drive the REAL shared {@link processBotMedia} through the adapter's own
 * `resolveDiscordMedia`, so they prove the two properties the adapter is
 * responsible for:
 *
 * 1. The Discord attachment's declared `size` reaches the shared pipeline, so an
 *    oversize attachment is rejected before the CDN is ever contacted.
 * 2. The download thunk honours the byte cap it is handed — a CDN that lies
 *    about (or omits) the size is truncated and cancelled, never buffered whole.
 *
 * Only discord.js Message shapes and the network are faked; the size decision,
 * the reply copy and the capped read are all production code.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GaiaClient } from "../../../../libs/shared/ts/src/bots/api";
import type {
  BotFileData,
  BotUserContext,
} from "../../../../libs/shared/ts/src/bots/types";
import type {
  IncomingAttachment,
  MediaBatchOutcome,
} from "../../../../libs/shared/ts/src/bots/utils";
import {
  BOT_MEDIA_LIMITS,
  mediaKindFromMime,
  processBotMedia,
} from "../../../../libs/shared/ts/src/bots/utils";

vi.mock("@gaia/shared/bots", async () => {
  const { makeGaiaSharedMock } = await import("../shared/mocks/gaiaSharedBase");
  const real = await import("../../../../libs/shared/ts/src/bots/utils");
  return makeGaiaSharedMock("discord", {
    streamingDefaults: {
      discord: { editIntervalMs: 1200, streaming: false, platform: "discord" },
    },
    converters: {
      mediaKindFromMime: vi.fn(real.mediaKindFromMime),
      fetchBytesCapped: vi.fn(real.fetchBytesCapped),
      friendlyMediaError: vi.fn(real.friendlyMediaError),
    },
  });
});

import { fetchBytesCapped, MEDIA_READ_TIMEOUT_MS } from "@gaia/shared/bots";
import type { Message } from "discord.js";
import { DiscordAdapter } from "../../discord/src/adapter";

const CHUNK = 1024 * 1024;
const USER_ID = "user-123";
const CHANNEL_ID = "channel-abc";

let produced = 0;
let cancelled = false;
let fetchedUrls: string[] = [];

function endlessCdn(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      fetchedUrls.push(url);
      return Promise.resolve({
        ok: true,
        status: 200,
        body: new ReadableStream<Uint8Array>({
          pull(controller) {
            produced += CHUNK;
            controller.enqueue(new Uint8Array(CHUNK).fill(1));
          },
          cancel() {
            cancelled = true;
          },
        }),
      });
    }),
  );
}

function makeMessage(size: number): Message {
  return {
    channelId: CHANNEL_ID,
    attachments: new Map([
      [
        "att-1",
        {
          url: "https://cdn.discord.test/photo.jpg",
          name: "photo.jpg",
          contentType: "image/jpeg",
          size,
        },
      ],
    ]),
    stickers: { size: 0 },
    flags: { has: () => false },
  } as unknown as Message;
}

const fakeGaia = {
  uploadFile: vi.fn(
    async (): Promise<BotFileData> => ({
      fileId: "file-1",
      url: "https://gaia.test/file-1",
      filename: "photo.jpg",
      type: "image/jpeg",
    }),
  ),
  getPricingUrl: () => "https://gaia.test/pricing",
} as unknown as GaiaClient;

function buildAdapter(): DiscordAdapter {
  const adapter = new DiscordAdapter();
  (adapter as unknown as { gaia: GaiaClient }).gaia = fakeGaia;
  return adapter;
}

/** Runs the (single) attachment the adapter hands over through the real processBotMedia. */
function useRealPipeline(adapter: DiscordAdapter): void {
  (
    adapter as unknown as {
      resolveIncomingMedia: (
        items: IncomingAttachment[],
        userId: string,
        channelId?: string,
      ) => Promise<MediaBatchOutcome>;
    }
  ).resolveIncomingMedia = async (items, userId, channelId) => {
    const [{ media, download }] = items;
    const outcome = await processBotMedia(fakeGaia, media, download, {
      platform: "discord",
      platformUserId: userId,
      channelId,
    } as BotUserContext);
    return outcome.action === "reply"
      ? { notice: outcome.text, text: "", attachments: [] }
      : { notice: "", text: outcome.text, attachments: outcome.attachments };
  };
}

let sent: string[] = [];

function resolveMedia(
  adapter: DiscordAdapter,
  message: Message,
  caption = "",
): Promise<MediaBatchOutcome | null> {
  return (
    adapter as unknown as {
      resolveDiscordMedia: (
        message: Message,
        caption: string,
        userId: string,
        send: (text: string) => Promise<unknown>,
      ) => Promise<MediaBatchOutcome | null>;
    }
  ).resolveDiscordMedia(message, caption, USER_ID, async (text) => {
    sent.push(text);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  produced = 0;
  cancelled = false;
  fetchedUrls = [];
  sent = [];
  endlessCdn();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DiscordAdapter - inbound media size gating", () => {
  it("rejects an attachment whose declared size exceeds the file limit without contacting the CDN", async () => {
    const adapter = buildAdapter();
    useRealPipeline(adapter);

    const outcome = await resolveMedia(
      adapter,
      makeMessage(BOT_MEDIA_LIMITS.file + 1),
    );

    expect(outcome?.attachments).toEqual([]);
    expect(sent).toEqual([
      "That file is too large to process (limit: 10 MB). Please share a smaller file.",
    ]);
    expect(fetchedUrls).toEqual([]);
    expect(fakeGaia.uploadFile).not.toHaveBeenCalled();
  });

  it("truncates and cancels a CDN stream that outruns the declared size", async () => {
    const adapter = buildAdapter();
    useRealPipeline(adapter);

    const outcome = await resolveMedia(adapter, makeMessage(1024));

    expect(fetchedUrls).toEqual(["https://cdn.discord.test/photo.jpg"]);
    expect(cancelled).toBe(true);
    expect(produced).toBeLessThanOrEqual(BOT_MEDIA_LIMITS.file + 2 * CHUNK);
    expect(outcome?.attachments).toEqual([]);
    expect(sent).toHaveLength(1);
    expect(sent[0]).toContain("too large");
    expect(fakeGaia.uploadFile).not.toHaveBeenCalled();
  });

  it("uploads an attachment that fits, passing the bytes the CDN actually returned", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        body: new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new Uint8Array([7, 7, 7]));
            controller.close();
          },
        }),
      })),
    );
    const adapter = buildAdapter();
    useRealPipeline(adapter);

    const outcome = await resolveMedia(adapter, makeMessage(3), "what is this");

    expect(outcome).toMatchObject({ text: "what is this" });
    expect(outcome?.attachments.map((a) => a.fileId)).toEqual(["file-1"]);
    expect(sent).toEqual([]);
    expect(fakeGaia.uploadFile).toHaveBeenCalledTimes(1);
    const uploaded = vi.mocked(fakeGaia.uploadFile).mock.calls[0][0] as {
      data: Buffer;
    };
    expect(Array.from(uploaded.data)).toEqual([7, 7, 7]);
  });

  it("forwards the cap it is handed to the CDN download instead of ignoring it", async () => {
    const adapter = buildAdapter();
    const resolve = (
      adapter as unknown as {
        resolveIncomingMedia: ReturnType<typeof vi.fn>;
      }
    ).resolveIncomingMedia;

    await resolveMedia(adapter, makeMessage(1024));

    const download = resolve.mock.calls[0][0][0].download as (
      maxBytes: number,
    ) => Promise<Uint8Array>;
    const bytes = await download(4096);

    expect(bytes.byteLength).toBe(4096);
    expect(cancelled).toBe(true);
    expect(vi.mocked(fetchBytesCapped).mock.calls[0][3]).toBe(
      MEDIA_READ_TIMEOUT_MS,
    );
  });

  it("hands the shared pipeline the attachment's declared size", async () => {
    const adapter = buildAdapter();
    const resolve = (
      adapter as unknown as {
        resolveIncomingMedia: ReturnType<typeof vi.fn>;
      }
    ).resolveIncomingMedia;

    await resolveMedia(adapter, makeMessage(555_000));

    expect(resolve.mock.calls[0][0][0].media).toMatchObject({
      kind: mediaKindFromMime("image/jpeg"),
      sizeBytes: 555_000,
    });
  });

  it("hands the shared pipeline every attachment, each with its own download", async () => {
    const adapter = buildAdapter();
    const resolve = (
      adapter as unknown as {
        resolveIncomingMedia: ReturnType<typeof vi.fn>;
      }
    ).resolveIncomingMedia;
    const message = makeMessage(100);
    (message.attachments as unknown as Map<string, unknown>).set("att-2", {
      url: "https://cdn.discord.test/second.png",
      name: "second.png",
      contentType: "image/png",
      size: 200,
    });

    await resolveMedia(adapter, message, "compare");

    const items = resolve.mock.calls[0][0] as {
      media: { sizeBytes: number; caption: string };
      download: (maxBytes: number) => Promise<Uint8Array>;
    }[];
    expect(items.map((i) => i.media.sizeBytes)).toEqual([100, 200]);
    expect(items.every((i) => i.media.caption === "compare")).toBe(true);
    await items[1].download(10);
    expect(fetchedUrls).toEqual(["https://cdn.discord.test/second.png"]);
  });
});
