/**
 * Utility functions for handling NEW_MESSAGE_BREAK tokens in chat messages
 * Enables WhatsApp-style multiple bubble responses from a single message
 */

export function splitMessageByBreaks(content: string): string[] {
  // Return empty array for empty/whitespace content
  if (!content?.trim()) {
    return [];
  }

  if (!content.includes("<NEW_MESSAGE_BREAK>")) {
    return [content];
  }

  return content
    .split("<NEW_MESSAGE_BREAK>")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}
