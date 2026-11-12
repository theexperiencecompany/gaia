import type { SendMessageRequest } from "@shared/api/generated";
import {
  createLiveConversationStore,
  type LiveConversation as SharedLiveConversation,
} from "@shared/conversation/live";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";

/** The request as this device built it: a picked workflow carries every step's id and category. */
type LocalSendBody = Omit<SendMessageRequest, "selected_workflow"> & {
  selected_workflow?: WorkflowData | null;
};

/**
 * A message this device sent: the request it POSTs and the attachments' display data,
 * which the request names by id only and the bubble shows before the entry arrives.
 */
export interface LocalSend {
  body: LocalSendBody;
  fileData: FileData[];
  failed: boolean;
}

export type LiveConversation = SharedLiveConversation<LocalSend>;

export const {
  useLiveConversationStore,
  liveConversation,
  useLiveConversation,
} = createLiveConversationStore<LocalSend>();
