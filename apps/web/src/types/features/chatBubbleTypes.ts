import type {
  BotMessageData,
  SetImageDataType,
  UserMessageData,
} from "./baseMessageTypes";

// Chat bubble props extending base message data
export interface ChatBubbleUserProps extends UserMessageData {}

export interface ChatBubbleBotProps extends BotMessageData {}

/** A bubble's neighbours from the same sender: a run reads as one group, chrome on its last bubble. */
export interface BubbleGrouping {
  withPrev: boolean;
  withNext: boolean;
}

// Re-export the SetImageDataType for backwards compatibility
export type { SetImageDataType };
