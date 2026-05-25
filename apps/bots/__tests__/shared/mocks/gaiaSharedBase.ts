/**
 * Shared @gaia/shared mock factory for bot adapter tests.
 *
 * All adapter tests mock @gaia/shared identically except for platform name,
 * STREAMING_DEFAULTS, and platform-specific converters. This factory avoids
 * duplicating the common ~40-line BaseBotAdapter stub across every test file.
 *
 * Usage in a test file:
 *
 *   vi.mock("@gaia/shared", async () => {
 *     const { makeGaiaSharedMock } = await import("../shared/mocks/gaiaSharedBase");
 *     return makeGaiaSharedMock("whatsapp", {
 *       streamingDefaults: { whatsapp: { editIntervalMs: 2000, streaming: false, platform: "whatsapp" } },
 *       converters: { convertToWhatsAppMarkdown: vi.fn((t: string) => t) },
 *       defaultRichMarkdown: "*GAIA Help*\nUse /gaia to chat",
 *     });
 *   });
 */

import { vi } from "vitest";

interface GaiaSharedMockOptions {
  /** Per-platform streaming configuration object */
  streamingDefaults: Record<string, unknown>;
  /** Platform-specific converter mocks to merge into the returned object */
  converters?: Record<string, ReturnType<typeof vi.fn>>;
  /** Return value of the richMessageToMarkdown mock */
  defaultRichMarkdown?: string;
}

/**
 * Creates the @gaia/shared mock object with a BaseBotAdapter stub and shared
 * helper mocks. Callers supply platform-specific overrides.
 */
export function makeGaiaSharedMock(
  platform: string,
  options: GaiaSharedMockOptions,
): Record<string, unknown> {
  const {
    streamingDefaults,
    converters = {},
    defaultRichMarkdown = "**GAIA**\nHello",
  } = options;

  const formatBotErrorImpl = (err: unknown): string =>
    err instanceof Error ? `Error: ${err.message}` : "Something went wrong";

  const BaseBotAdapter = class {
    platform = platform;
    gaia = { getPricingUrl: () => "https://gaia.test/pricing" };
    config = {};
    commands = new Map();
    analytics = undefined;

    protected async dispatchCommand(
      name: string,
      target: {
        sendEphemeral: (
          t: string,
        ) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
      },
      args: Record<string, string | number | boolean | undefined> = {},
      rawText?: string,
    ) {
      const cmd = (
        this.commands as Map<string, { execute: (p: unknown) => Promise<void> }>
      ).get(name);
      if (!cmd) {
        await target.sendEphemeral(`Unknown command: /${name}`);
        return;
      }
      try {
        await cmd.execute({ gaia: this.gaia, target, ctx: {}, args, rawText });
      } catch (error) {
        const errMsg = formatBotErrorImpl(error);
        try {
          await target.sendEphemeral(errMsg);
        } catch {
          // Target may be expired
        }
      }
    }

    protected buildContext(userId: string, channelId?: string) {
      return { platform: this.platform, platformUserId: userId, channelId };
    }

    // --- Base helpers added for the class-based pattern. Stubbed with real-ish
    // behavior so adapter tests exercise the adapter's own wiring; the real
    // implementations are covered by shared tests (media.test.ts, base behavior).

    private readonly _welcomed = new Set<string>();
    protected shouldSendWelcome(userId: string): boolean {
      if (this._welcomed.has(userId)) return false;
      this._welcomed.add(userId);
      return true;
    }

    protected startTypingIndicator(
      sendTyping: () => Promise<unknown>,
      _refreshMs: number,
    ): () => void {
      void sendTyping().catch(() => {});
      return () => {};
    }

    // Default: route media to a chat turn with no attachments. Tests that care
    // about a specific outcome (upload, transcribe, reject) override this via
    // (adapter as ...).resolveIncomingMedia.mockResolvedValueOnce(...).
    resolveIncomingMedia = vi.fn(async (media: { caption?: string }) => ({
      action: "chat" as const,
      text: media.caption ?? "media",
      attachments: [] as unknown[],
    }));
  };

  const createBotLogger = vi.fn(() => ({
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  }));

  const hashLogIdentifier = vi.fn(
    (value: string | number | undefined | null) => {
      if (value === undefined || value === null) return undefined;
      return `h_${String(value)}`;
    },
  );

  const sanitizeErrorForLog = vi.fn((error: unknown) => {
    if (error instanceof Error) {
      return { error_name: error.name, error_message: error.message };
    }
    return { error_name: "Unknown", error_message: String(error) };
  });

  return {
    BaseBotAdapter,
    createBotLogger,
    hashLogIdentifier,
    sanitizeErrorForLog,
    formatBotError: vi.fn((err: unknown) =>
      err instanceof Error ? `Error: ${err.message}` : "Something went wrong",
    ),
    handleStreamingChat: vi.fn().mockResolvedValue(undefined),
    STREAMING_DEFAULTS: streamingDefaults,
    // renderForPlatform is the shared non-streaming chokepoint. In adapter tests
    // @gaia/shared is mocked, so conversion does not actually happen here — the
    // identity mock returns RAW text and the real conversion is covered by the
    // shared formatters tests.
    renderForPlatform: vi.fn((text: string) => text),
    richMessageToMarkdown: vi.fn().mockReturnValue(defaultRichMarkdown),
    parseTextArgs: vi.fn((text: string) => ({
      subcommand: text.split(" ")[0] || undefined,
    })),
    // Shared helpers the adapters import. Real-ish stubs so adapter tests can
    // assert observable behavior (e.g. that the auth link/url is sent); the
    // exact production copy is asserted in the shared formatters/media tests.
    buildAuthLinkMessage: vi.fn(
      (url: string) => `Link your account to GAIA: ${url}`,
    ),
    htmlToPlainText: vi.fn((html: string) =>
      html
        .replaceAll(/<[^>]+>/g, "")
        .replaceAll(/&lt;/g, "<")
        .replaceAll(/&gt;/g, ">")
        .replaceAll(/&amp;/g, "&"),
    ),
    friendlyMediaError: vi.fn(
      (kind: string) => `Couldn't process that ${kind}.`,
    ),
    unsupportedMediaMessage: vi.fn(
      (kind: string) => `I can't process ${kind} yet.`,
    ),
    extractSubcommandArgs: vi.fn((name: string, raw?: string) =>
      name === "todo" || name === "workflow"
        ? { subcommand: (raw ?? "").trim().split(/\s+/)[0] || "list" }
        : {},
    ),
    ...converters,
  };
}
