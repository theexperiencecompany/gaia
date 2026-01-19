/**
 * Checks if a string consists only of emojis and whitespace.
 * Uses unicode property escapes for high accuracy with modern emojis.
 */
export const isOnlyEmojis = (text: string | null | undefined): boolean => {
  if (!text) return false;
  const trimmed = text.trim();
  if (!trimmed) return false;

  // Regex breakdown:
  // \p{Extended_Pictographic}: Matches most emoji characters
  // \p{Emoji_Presentation}: Matches standard emoji presentation characters
  // \u200d: Zero Width Joiner
  // \ufe0f: Variation Selector-16
  // \u20e3: Combining Enclosing Keycap
  // \s: Whitespace

  // We use a grouping (...) instead of character class [...] for property escapes to be safe
  // safely matching any of these characters/sequences one or more times.
  // Note: Inside [], property escapes are allowed in modern JS engines (V8).
  // But let's use a robust pattern.
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
export const getEmojiCount = (text: string | null | undefined): number => {
  if (!text) return 0;

  try {
    const segmenter = new Intl.Segmenter("en", { granularity: "grapheme" });
    const emojiRegex =
      /^(?:\p{Extended_Pictographic}|\p{Emoji_Presentation}|\p{Emoji_Modifier_Base}|\p{Emoji_Modifier}|\u200d|\ufe0f|\u20e3)+$/u;
    let count = 0;
    for (const { segment } of segmenter.segment(text)) {
      // Only count if the segment matches emoji patterns
      if (emojiRegex.test(segment)) {
        count++;
      }
    }
    return count;
  } catch {
    // Fallback if Intl.Segmenter is not available
    // Use regex to match emoji sequences
    const emojiRegex =
      /(?:\p{Extended_Pictographic}|\p{Emoji_Presentation}|\p{Emoji_Modifier_Base}|\p{Emoji_Modifier}|\u200d|\ufe0f|\u20e3)+/gu;
    const matches = text.match(emojiRegex);
    return matches ? matches.length : 0;
  }
};
