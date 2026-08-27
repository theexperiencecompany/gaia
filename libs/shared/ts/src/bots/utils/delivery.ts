/**
 * Size-aware delivery of a finished string to a platform.
 *
 * The rule this module exists to enforce: text over a platform's size limit is
 * split into more messages, never cut short. A "... (truncated)" suffix throws
 * away content the user asked for to save a second API call that costs nothing.
 *
 * Lives in its own module because it needs both the chunker (`./text`) and the
 * platform renderers (`./formatters`), and `formatters` already imports
 * `text` — putting it in either would close an import cycle.
 */

import type { PlatformName } from "../types";
import { renderForPlatform } from "./formatters";
import { chunkResponse } from "./text";

/**
 * Sends `text` through `send`, split across as many messages as the platform's
 * limit requires.
 *
 * Chunks are measured by their RENDERED length, because `send` is an adapter
 * entry point and every adapter runs its argument through `renderForPlatform`
 * before it reaches the API — and rendering grows text (Telegram's HTML escapes
 * `&` to `&amp;`, wraps `**bold**` in `<b>`). Sizing the raw markdown instead
 * lets a chunk that looks like it fits get rejected by the platform.
 *
 * @param send - The adapter sender (`target.send` / `target.sendEphemeral`).
 * @param text - Raw markdown to deliver in full.
 * @param platform - Target platform, selecting both limit and renderer.
 */
export async function sendChunked(
  send: (text: string) => Promise<unknown>,
  text: string,
  platform: PlatformName,
): Promise<void> {
  const render = (chunk: string): string => renderForPlatform(chunk, platform);
  for (const chunk of chunkResponse(text, platform, render)) {
    await send(chunk);
  }
}
