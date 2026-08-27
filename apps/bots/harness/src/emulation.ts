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
 * The single residual is {@link PlatformEmulation.supportsEdit}: whether a
 * platform can edit a delivered message in place, or must send a fresh one. That
 * bit lives in each real adapter's send wiring (grammY `editMessageText`, Slack
 * `chat.update`, Discord `message.edit`) rather than in any shared table, so it
 * is declared here — and the conformance suite pins every entry to the real
 * adapter, failing CI the moment it diverges.
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
   * Whether the platform edits a delivered bubble in place. `false` means an
   * "edit" is really a new message (WhatsApp, whose Cloud API has no edit).
   * Mirrors the real adapter's send wiring; locked by the conformance suite.
   *
   * - discord: `Message.edit` / `interaction.editReply` → true
   * - slack: `chat.update` → true
   * - telegram: `editMessageText` → true
   * - whatsapp: no edit API, `sendWhatsAppText` sends new → false
   */
  supportsEdit: boolean;
}

/** Residual capability map — see {@link PlatformEmulation.supportsEdit}. */
const SUPPORTS_EDIT: Record<PlatformName, boolean> = {
  discord: true,
  slack: true,
  telegram: true,
  whatsapp: false,
  imessage: false,
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
