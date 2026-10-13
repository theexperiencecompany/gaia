/**
 * Checks if a string consists only of emojis and whitespace.
 * Uses unicode property escapes for high accuracy with modern emojis.
 */
export const isOnlyEmojis = (text: string | null | undefined): boolean => {
  if (!text) return false;
  const trimmed = text.trim();
  if (!trimmed) return false;

  // Matches Extended_Pictographic / Emoji_Presentation / Emoji_Modifier(_Base)
  // plus ZWJ, VS16, and the combining keycap (\u20e3) used in flag/keycap emoji.
  const emojiRegex =
    /^(?:\p{Extended_Pictographic}|\p{Emoji_Presentation}|\p{Emoji_Modifier_Base}|\p{Emoji_Modifier}|\u200d|\ufe0f|\u20e3|\s)+$/u;

  // Exclude strings that are just digits/punctuation without being emoji sequences
  return (
    emojiRegex.test(trimmed) &&
    !/^[0-9\s]+$/.test(trimmed) &&
    !/^[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?\s]+$/.test(trimmed)
  );
};

/**
 * Counts the number of visually distinct emojis in the text.
 * Uses Intl.Segmenter for grapheme clustering to handle compound emojis correctly.
 */
const graphemeSegmenter =
  typeof Intl !== "undefined" && "Segmenter" in Intl
    ? new Intl.Segmenter("en", { granularity: "grapheme" })
    : null;

export const getEmojiCount = (text: string | null | undefined): number => {
  if (!text) return 0;

  if (!graphemeSegmenter) {
    // Fallback if Intl.Segmenter is not available
    // Use regex to match emoji sequences
    const emojiRegex =
      /(?:\p{Extended_Pictographic}|\p{Emoji_Presentation}|\p{Emoji_Modifier_Base}|\p{Emoji_Modifier}|\u200d|\ufe0f|\u20e3)+/gu;
    const matches = text.match(emojiRegex);
    return matches ? matches.length : 0;
  }

  const emojiRegex =
    /^(?:\p{Extended_Pictographic}|\p{Emoji_Presentation}|\p{Emoji_Modifier_Base}|\p{Emoji_Modifier}|\u200d|\ufe0f|\u20e3)+$/u;
  let count = 0;
  for (const { segment } of graphemeSegmenter.segment(text)) {
    // Only count if the segment matches emoji patterns
    if (emojiRegex.test(segment)) {
      count++;
    }
  }
  return count;
};
