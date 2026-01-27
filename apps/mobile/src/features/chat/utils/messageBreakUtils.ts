export function splitMessageByBreaks(content: string): string[] {
  if (!content || !content.includes("<NEW_MESSAGE_BREAK>")) {
    return [content];
  }

  return content
    .split("<NEW_MESSAGE_BREAK>")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}
