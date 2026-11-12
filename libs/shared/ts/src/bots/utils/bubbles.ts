/**
 * The messages a bot sends for one finished assistant reply.
 *
 * The streamed reply and every background delivery (executor results,
 * reminders, workflow results) split through here, so a reply arrives as the
 * same messages whichever path carried it.
 */

import { splitMessageByBreaks } from "../../utils/messageBubbles";
import type { PlatformName } from "../types";
import { chunkResponse } from "./text";

/** The gap between two bubbles sent back to back, so they land like texts a person sends. */
export const BUBBLE_PAUSE_MS = 600;

/** The model's bubbles, each cut to the platform's limit measured by its rendered length. */
export function deliverableBubbles(
  text: string,
  platform: PlatformName,
  render: (chunk: string) => string,
): string[][] {
  return splitMessageByBreaks(text).map((bubble) =>
    chunkResponse(bubble, platform, render),
  );
}
