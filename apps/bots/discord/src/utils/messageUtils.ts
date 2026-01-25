/**
 * Splits a message by <NEW_MESSAGE_BREAK> markers and returns an array of message parts.
 * Filters out empty parts after trimming.
 *
 * @param content - The message content potentially containing break markers.
 * @returns Array of message parts to send separately.
 */
export function splitMessageByBreaks(content: string): string[] {
  if (!content || !content.includes("<NEW_MESSAGE_BREAK>")) {
    return [content];
  }

  return content
    .split("<NEW_MESSAGE_BREAK>")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

/**
 * Delays execution for a specified number of milliseconds.
 *
 * @param ms - Milliseconds to delay.
 */
export function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
