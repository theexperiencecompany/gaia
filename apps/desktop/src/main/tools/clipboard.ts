/**
 * Clipboard access for the desktop tool bridge.
 *
 * @module tools/clipboard
 */

import { clipboard } from "electron";

export function readClipboardText(): { text: string } {
  return { text: clipboard.readText() };
}

export function writeClipboardText(text: string): void {
  clipboard.writeText(text);
}
