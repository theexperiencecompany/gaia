import { SystemPurpose } from "@/features/chat/api/chatApi";

/**
 * Check if text bubble should be shown (considering system-generated conversations)
 */
export const shouldShowTextBubble = (
  text: string,
  isConvoSystemGenerated?: boolean,
  systemPurpose?: SystemPurpose,
): boolean => {
  // Don't show text bubble when conversation is system generated for mail_processing
  const isEmailProcessingSystem =
    isConvoSystemGenerated && systemPurpose === SystemPurpose.EMAIL_PROCESSING;

  if (isEmailProcessingSystem) {
    return false;
  }

  // Check if text has meaningful content (not null, undefined, empty, or just whitespace)
  return text != null && text.trim().length > 0;
};
