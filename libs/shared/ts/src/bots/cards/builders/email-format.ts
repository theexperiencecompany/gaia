import { formatRelativeDate } from "../../../utils/formatters";

/** Gmail's own label for a message without one. */
export const NO_SUBJECT = "(no subject)";

/** `"Ada Lovelace" <ada@example.com>`: the display name, then the address. */
const NAMED_ADDRESS = /^"?([^"<]*)"?\s*<([^>]+)>$/;

/** Who sent it, the way a mail client lists it: the display name, else the address. */
export function senderName(from: string): string {
  const match = NAMED_ADDRESS.exec(from.trim());
  if (!match) return from.trim();
  return match[1].trim() || match[2].trim();
}

/**
 * When it arrived, relative ("3h ago") so the bot server's own timezone never
 * shows. Gmail's `time` is whatever the Date header said, so one that does not
 * parse is shown as sent rather than as "Invalid Date".
 */
export function emailTimeLabel(time: string | undefined): string | undefined {
  if (!time) return undefined;
  return Number.isNaN(Date.parse(time)) ? time : formatRelativeDate(time);
}
