/**
 * Utility to extract thinking content from AI response text
 * Handles thinking tags like <thinking>...</thinking>
 */

export interface ParsedContent {
  thinking: string | null;
  cleanText: string;
}

/**
 * Extracts thinking content from text and returns cleaned text without thinking tags
 */
export function parseThinkingFromText(text: string): ParsedContent {
  if (!text) {
    return { thinking: null, cleanText: text };
  }

  // Match <thinking>...</thinking> tags (case-insensitive, multiline, non-greedy)
  const thinkingRegex = /<thinking>([\s\S]*?)<\/thinking>/gi;
  const matches = text.match(thinkingRegex);

  if (!matches || matches.length === 0) {
    return { thinking: null, cleanText: text };
  }

  // Extract all thinking content
  const thinkingParts: string[] = [];
  matches.forEach((match) => {
    const content = match.replace(/<\/?thinking>/gi, "").trim();
    if (content) {
      thinkingParts.push(content);
    }
  });

  // Remove thinking tags from the original text
  const cleanText = text.replace(thinkingRegex, "").trim();

  // Join all thinking parts with line breaks
  const thinking = thinkingParts.length > 0 ? thinkingParts.join("\n\n") : null;

  return { thinking, cleanText };
}
