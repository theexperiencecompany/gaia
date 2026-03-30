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
    gaia = {};
    config = {};
    commands = new Map();

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
  };

  return {
    BaseBotAdapter,
    formatBotError: vi.fn((err: unknown) =>
      err instanceof Error ? `Error: ${err.message}` : "Something went wrong",
    ),
    handleStreamingChat: vi.fn().mockResolvedValue(undefined),
    STREAMING_DEFAULTS: streamingDefaults,
    richMessageToMarkdown: vi.fn().mockReturnValue(defaultRichMarkdown),
    parseTextArgs: vi.fn((text: string) => ({
      subcommand: text.split(" ")[0] || undefined,
    })),
    ...converters,
  };
}
