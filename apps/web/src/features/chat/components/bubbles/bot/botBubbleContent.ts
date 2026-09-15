import type { SystemPurpose } from "@/features/chat/api/chatApi";

interface BotBubbleContentInput {
  text: string | undefined;
  showsTextBubble: boolean;
  error: unknown;
  imageData: unknown;
  isConvoSystemGenerated: boolean | undefined;
  systemPurpose: SystemPurpose | undefined;
  toolDataLength: number | undefined;
  emailProcessingPurpose: SystemPurpose;
}

/** What a bot bubble has to show: the quiet error bubble for a failed turn
 *  with no text, and whether there is anything at all to render. Pure, so the
 *  component itself stays flat. */
export function describeBotBubbleContent({
  text,
  showsTextBubble,
  error,
  imageData,
  isConvoSystemGenerated,
  systemPurpose,
  toolDataLength,
  emailProcessingPurpose,
}: BotBubbleContentInput): { hasError: boolean; hasContent: boolean } {
  const hasError = !showsTextBubble && !!error;
  const isEmailProcessing =
    !!isConvoSystemGenerated && systemPurpose === emailProcessingPurpose;
  const hasContent =
    !!imageData || !!text || hasError || isEmailProcessing || !!toolDataLength;
  return { hasError, hasContent };
}
