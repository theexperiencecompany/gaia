import {
  BASE_MESSAGE_KEYS,
  BASE_MESSAGE_SCHEMA,
  type BaseMessageData,
} from "@/config/registries/baseMessageRegistry";
import { TOOLS_MESSAGE_KEYS } from "@/config/registries/toolRegistry";
import { SystemPurpose } from "@/features/chat/api/chatApi";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import type {
  ConversationMessage,
  MessageType,
} from "@/types/features/convoTypes";

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

/**
 * Comprehensive check to determine if a bot message has any meaningful content
 */
export const isBotMessageEmpty = (props: ChatBubbleBotProps): boolean => {
  const { text, loading, isConvoSystemGenerated, systemPurpose } = props;

  // Loading messages are considered not empty
  if (loading) return false;

  // Check if any tool-specific content exists
  const hasToolContent = TOOLS_MESSAGE_KEYS.some((key) => {
    const value = props[key];
    return value != null && value !== undefined;
  });

  // Check if text content is meaningful
  const hasTextContent = shouldShowTextBubble(
    text,
    isConvoSystemGenerated,
    systemPurpose,
  );

  // Message is empty only if it has neither tool content nor meaningful text
  return !hasToolContent && !hasTextContent;
};

/**
 * Filter out empty message pairs from a conversation
 * This will remove user+bot message pairs where the bot response is completely empty
 */
export const filterEmptyMessagePairs = (
  messages: MessageType[],
  isConvoSystemGenerated: boolean = false,
  systemPurpose?: SystemPurpose,
): MessageType[] => {
  const filteredMessages: MessageType[] = [];

  for (let i = 0; i < messages.length; i++) {
    const currentMessage = messages[i];

    if (currentMessage.type === "user" && i + 1 < messages.length) {
      const nextMessage = messages[i + 1];

      if (nextMessage.type === "bot") {
        // Build base fields from BASE_MESSAGE_KEYS
        const baseFields: BaseMessageData = Object.fromEntries(
          BASE_MESSAGE_KEYS.map((key) => [
            key,
            key in nextMessage
              ? (nextMessage as ConversationMessage)[key]
              : BASE_MESSAGE_SCHEMA[key],
          ]),
        ) as BaseMessageData;
        // Build the full botProps object
        const botProps: ChatBubbleBotProps = {
          ...baseFields,
          text: nextMessage.response || "",
          loading: nextMessage.loading,
          setOpenImage: () => {},
          setImageData: () => {},
          systemPurpose,
          isConvoSystemGenerated,
        };

        // Always include the user message
        filteredMessages.push(currentMessage);
        // Only include bot message if it has content
        if (!isBotMessageEmpty(botProps)) {
          filteredMessages.push(nextMessage);
        }
        i++;
      } else {
        filteredMessages.push(currentMessage);
      }
    } else if (currentMessage.type === "bot") {
      // Standalone bot message (not part of a pair)
      const baseFields: BaseMessageData = Object.fromEntries(
        BASE_MESSAGE_KEYS.map((key) => [
          key,
          key in currentMessage
            ? (currentMessage as ConversationMessage)[key]
            : BASE_MESSAGE_SCHEMA[key],
        ]),
      ) as BaseMessageData;
      const botProps: ChatBubbleBotProps = {
        ...baseFields,
        text: currentMessage.response || "",
        loading: currentMessage.loading,
        setOpenImage: () => {},
        setImageData: () => {},
        systemPurpose,
        isConvoSystemGenerated,
      };

      if (!isBotMessageEmpty(botProps)) {
        filteredMessages.push(currentMessage);
      }
    } else {
      filteredMessages.push(currentMessage);
    }
  }

  return filteredMessages;
};
