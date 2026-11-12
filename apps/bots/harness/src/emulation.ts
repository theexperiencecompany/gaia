/**
 * Per-platform emulation descriptor.
 *
 * FIDELITY CONTRACT: the harness never keeps its own copy of a platform's
 * behavior tables. Everything a real adapter would look up in `@gaia/shared`
 * is pulled *live* here — the character limit from {@link PLATFORM_LIMITS}, the
 * streaming cadence from {@link STREAMING_DEFAULTS}, and the markdown converter
 * from {@link renderForPlatform}. If the shared value changes, the harness
 * changes with it; there is nothing to drift.
 *
 * Two residuals live in each real adapter's wiring rather than in any shared
 * table, so they are declared here: {@link PlatformEmulation.supportsEdit},
 * whether a platform can edit a delivered message in place (grammY
 * `editMessageText`, Slack `chat.update`, Discord `message.edit`) — pinned to
 * the real adapter by the conformance suite — and
 * {@link PlatformEmulation.serializesInbound}, whether the adapter handles one
 * user's messages one at a time.
 */

import {
  PLATFORM_LIMITS,
  type PlatformName,
  renderForPlatform,
  STREAMING_DEFAULTS,
  type StreamingOptions,
} from "@gaia/shared/bots";

export interface PlatformEmulation {
  platform: PlatformName;
  /** Live from {@link PLATFORM_LIMITS} — never re-hardcoded. */
  limit: number;
  /** Live from {@link STREAMING_DEFAULTS} — throttle cadence + streaming flag. */
  streaming: StreamingOptions;
  /** Live from {@link renderForPlatform} — the platform's markdown converter. */
  render: (text: string) => string;
  /**
   * Whether the platform edits a delivered bubble in place (`false` = "edit" sends
   * a new message, e.g. WhatsApp — no edit API). Mirrors the real adapter's send
   * wiring; locked by the conformance suite: discord `Message.edit`/
   * `interaction.editReply`, slack `chat.update`, telegram `editMessageText` all
   * edit; whatsapp always sends new via `sendWhatsAppText`.
   */
  supportsEdit: boolean;
  /**
   * Whether the adapter can take back a bubble it streamed (grammY `deleteMessage`,
   * Slack `chat.delete`): the live platforms, whose retracted bubbles are deleted.
   */
  supportsDelete: boolean;
  /**
   * Whether the adapter handles a user's next message only after the previous
   * one's handler finished. Telegram: grammY's built-in polling awaits each
   * update in turn (`bot.js` handleUpdates). WhatsApp and iMessage: a per-user
   * promise queue in the adapter (`messageQueues`). Discord and Slack run every
   * event handler as it arrives.
   */
  serializesInbound: boolean;
}

/** Residual capability map — see {@link PlatformEmulation.supportsEdit}. */
const SUPPORTS_EDIT: Record<PlatformName, boolean> = {
  discord: true,
  slack: true,
  telegram: true,
  whatsapp: false,
  imessage: false,
};

/** Residual capability map — see {@link PlatformEmulation.supportsDelete}. */
const SUPPORTS_DELETE: Record<PlatformName, boolean> = {
  discord: false,
  slack: true,
  telegram: true,
  whatsapp: false,
  imessage: false,
};

/** Residual dispatch map — see {@link PlatformEmulation.serializesInbound}. */
const SERIALIZES_INBOUND: Record<PlatformName, boolean> = {
  discord: false,
  slack: false,
  telegram: true,
  whatsapp: true,
  imessage: true,
};

/**
 * Builds the emulation descriptor for `platform`, resolving every behavioral
 * value from the shared library at call time.
 */
export function resolveEmulation(platform: PlatformName): PlatformEmulation {
  const limit = PLATFORM_LIMITS[platform];
  if (limit === undefined) {
    throw new Error(`No PLATFORM_LIMITS entry for platform "${platform}"`);
  }
  const streaming = STREAMING_DEFAULTS[platform];
  if (!streaming) {
    throw new Error(`No STREAMING_DEFAULTS entry for platform "${platform}"`);
  }
  return {
    platform,
    limit,
    streaming,
    render: (text: string) => renderForPlatform(text, platform),
    supportsEdit: SUPPORTS_EDIT[platform],
    supportsDelete: SUPPORTS_DELETE[platform],
    serializesInbound: SERIALIZES_INBOUND[platform],
  };
}

/** Derived from the exhaustive SUPPORTS_EDIT record so a new PlatformName
 * can't be silently unemulatable. */
export const EMULATABLE_PLATFORMS: readonly PlatformName[] = Object.keys(
  SUPPORTS_EDIT,
) as PlatformName[];

/** Type guard: is `value` a platform the harness knows how to emulate? */
export function isEmulatablePlatform(value: string): value is PlatformName {
  return (EMULATABLE_PLATFORMS as readonly string[]).includes(value);
}
