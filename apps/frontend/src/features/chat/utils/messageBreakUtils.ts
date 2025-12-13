/**
 * Utility functions for handling NEW_MESSAGE_BREAK tokens in chat messages
 * Enables WhatsApp-style multiple bubble responses from a single message
 */

export function splitMessageByBreaks(content: string): string[] {
  if (!content || !content.includes("<NEW_MESSAGE_BREAK>")) {
    return [content]; // No breaks = single bubble
  }

  return content
    .split("<NEW_MESSAGE_BREAK>")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}
