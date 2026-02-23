import type { SystemPurpose } from "@/features/chat/api/chatApi";
import type {
  ChatBubbleBotProps,
  ChatBubbleUserProps,
  SetImageDataType,
} from "@/types/features/chatBubbleTypes";
import type { MessageType } from "@/types/features/convoTypes";

/**
 * Utility for transforming raw message data into typed props for chat components.
 *
 * Extracted from ChatRenderer to:
 * - Automatically map chat bubble props for bot and user messages instead of manually passing each key
 * - Separate data transformation from UI logic
 * - Provide type-safe prop mapping with function overloads
 * - Filter undefined values to prevent React warnings
 * - Enable easier testing and code reuse
 */

// Options interface for the function parameters
interface MessagePropsOptions {
  conversation?: {
    is_system_generated?: boolean;
    system_purpose?: SystemPurpose;
  };
  setImageData: React.Dispatch<React.SetStateAction<SetImageDataType>>;
  setOpenGeneratedImage: React.Dispatch<React.SetStateAction<boolean>>;
  setOpenMemoryModal: React.Dispatch<React.SetStateAction<boolean>>;
  onRetry?: (messageId: string) => void;
  isRetrying?: boolean;
}

// Function overloads for better type safety
export function getMessageProps(
  message: MessageType,
  messageType: "bot",
  options: MessagePropsOptions,
): ChatBubbleBotProps;
export function getMessageProps(
  message: MessageType,
  messageType: "user",
  options: MessagePropsOptions,
): ChatBubbleUserProps;
export function getMessageProps(
  message: MessageType,
  messageType: "bot" | "user",
  options: MessagePropsOptions,
): ChatBubbleBotProps | ChatBubbleUserProps {
  const {
    conversation,
    setImageData,
    setOpenGeneratedImage,
    setOpenMemoryModal,
    onRetry,
    isRetrying,
  } = options;

  // Extract all props from message, filtering out undefined values
  const { response, ...messageProps } = message;

  // Filter out undefined values dynamically
  const filteredProps = Object.fromEntries(
    Object.entries(messageProps).filter(([_, value]) => value !== undefined),
  );

  // Base props common to both bot and user messages
  const baseProps = {
    ...filteredProps,
    text: response || "", // Map response to text, ensure always a string
    message_id:
      messageType === "user" ? message.message_id || "" : message.message_id, // User fallback to empty string
    isConvoSystemGenerated: conversation?.is_system_generated || false,
    onRetry: onRetry ? () => onRetry(message.message_id || "") : undefined,
    isRetrying,
  };

  // Add bot-specific props if message type is 'bot'
  if (messageType === "bot") {
    return {
      ...baseProps,
      setImageData,
      setOpenImage: setOpenGeneratedImage,
      onOpenMemoryModal: () => setOpenMemoryModal(true),
      systemPurpose: conversation?.system_purpose,
    } as ChatBubbleBotProps;
  }

  // Return base props for user messages
  return baseProps as ChatBubbleUserProps;
}
