import type {
  BotMessageData,
  SetImageDataType,
  UserMessageData,
} from "./baseMessageTypes";

// Chat bubble props extending base message data
export interface ChatBubbleUserProps extends UserMessageData {}

export interface ChatBubbleBotProps extends BotMessageData {}

// Re-export the SetImageDataType for backwards compatibility
export type { SetImageDataType };
