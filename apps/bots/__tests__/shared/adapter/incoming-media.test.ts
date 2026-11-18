/**
 * The shared inbound-media pipeline on BaseBotAdapter: every adapter hands it
 * the message's attachments as a list, and it alone decides how many are read
 * and what the user is told about the rest. Runs the real processBotMedia;
 * only the GAIA client and the platform download are faked.
 */
import {
  BaseBotAdapter,
  BOT_MAX_FILES_PER_MESSAGE,
  type BotFileData,
  type IncomingAttachment,
  type MediaBatchOutcome,
} from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";

class TestAdapter extends BaseBotAdapter {
  readonly platform = "slack" as const;
  protected readonly defaultServerPort = 3201;

  // The abstract lifecycle contract, stubbed: these tests drive the media
  // pipeline directly and never boot a platform client.
  protected async initialize(): Promise<void> {
    /* no platform client under test */
  }
  protected async registerCommands(): Promise<void> {
    /* no commands under test */
  }
  protected async registerEvents(): Promise<void> {
    /* no events under test */
  }
  protected async start(): Promise<void> {
    /* nothing to connect */
  }
  protected async stop(): Promise<void> {
    /* nothing to disconnect */
  }
  protected async deliverOutbound(): Promise<void> {
    /* no outbound delivery under test */
  }
  protected async sendOutboundFile(): Promise<void> {
    /* no file delivery under test */
  }

  install(gaia: unknown): void {
    (this as unknown as { gaia: unknown }).gaia = gaia;
    (this as unknown as { analytics: unknown }).analytics = {
      capture: vi.fn(),
      alias: vi.fn(),
    };
  }

  intake(items: IncomingAttachment[]): Promise<MediaBatchOutcome> {
    return this.resolveIncomingMedia(items, "U1", "D1");
  }
}

function image(name: string, caption?: string): IncomingAttachment {
  return {
    media: {
      kind: "image",
      isVoiceNote: false,
      mimeType: "image/png",
      filename: name,
      sizeBytes: 3,
      caption,
    },
    download: async () => new Uint8Array([1, 2, 3]),
  };
}

function setup(upload: (filename: string) => Promise<BotFileData>) {
  const uploadFile = vi.fn(async (file: { filename: string }) =>
    upload(file.filename),
  );
  const adapter = new TestAdapter();
  adapter.install({
    uploadFile,
    checkAuthStatus: vi.fn(async () => ({ authenticated: false })),
    getPricingUrl: () => "https://gaia.test/pricing",
  });
  return { adapter, uploadFile };
}

const stored = async (filename: string): Promise<BotFileData> => ({
  fileId: `id-${filename}`,
  url: `https://gaia.test/${filename}`,
  filename,
  type: "image/png",
});

describe("BaseBotAdapter.resolveIncomingMedia", () => {
  it("reads every attachment in the message, not just the first", async () => {
    const { adapter, uploadFile } = setup(stored);

    const outcome = await adapter.intake([
      image("a.png", "compare these"),
      image("b.png", "compare these"),
      image("c.png", "compare these"),
    ]);

    expect(uploadFile).toHaveBeenCalledTimes(3);
    expect(outcome.attachments.map((a) => a.fileId)).toEqual([
      "id-a.png",
      "id-b.png",
      "id-c.png",
    ]);
    expect(outcome.text).toBe("compare these");
    expect(outcome.replies).toEqual([]);
  });

  it("reads up to the web composer's limit and tells the user how many it skipped", async () => {
    const { adapter, uploadFile } = setup(stored);
    const names = ["1", "2", "3", "4", "5", "6", "7"].map((n) => `${n}.png`);

    const outcome = await adapter.intake(names.map((n) => image(n)));

    expect(BOT_MAX_FILES_PER_MESSAGE).toBe(5);
    expect(uploadFile).toHaveBeenCalledTimes(5);
    expect(outcome.attachments).toHaveLength(5);
    expect(outcome.replies).toEqual([
      "Up to 5 files per message. Read the first 5, skipped 2.",
    ]);
  });

  it("keeps the other files when one upload fails, and says which kind failed", async () => {
    const { adapter } = setup(async (filename) => {
      if (filename === "big.png") {
        throw Object.assign(new Error("too large"), {
          response: { status: 413 },
        });
      }
      return stored(filename);
    });

    const outcome = await adapter.intake([image("big.png"), image("ok.png")]);

    expect(outcome.attachments.map((a) => a.fileId)).toEqual(["id-ok.png"]);
    expect(outcome.replies).toEqual([
      "That image is too large for me to process. Please share a smaller file.",
    ]);
  });
});
