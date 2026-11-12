import type { SendMessageRequest } from "@gaia/shared/api/generated";
import {
  createLiveConversationStore,
  type LiveConversation,
} from "@gaia/shared/conversation/live";
import type { ApiFileData } from "../api/chat-api";

/**
 * A message this device sent: the request it POSTs (resent unchanged on retry, so
 * the server's message id dedup holds), the attachments' display data the request
 * names by id only, and when it was sent, for the bubble shown before the entry.
 */
export interface MobileSend {
  body: SendMessageRequest;
  fileData: ApiFileData[];
  sentAt: string;
  failed: boolean;
}

export type MobileLiveConversation = LiveConversation<MobileSend>;

export const {
  useLiveConversationStore,
  liveConversation,
  useLiveConversation,
} = createLiveConversationStore<MobileSend>();
