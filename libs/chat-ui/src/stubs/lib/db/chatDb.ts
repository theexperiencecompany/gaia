/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import { EventEmitter } from "events";

import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import type { SystemPurpose } from "@/features/chat/api/chatApi";
import type { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import type { TodoProgressData } from "@/types/features/todoProgressTypes";
import type { ImageData, MemoryData } from "@/types/features/toolDataTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";

export interface IConversation {
  id: string;
  title: string;
  description?: string;
  userId?: string;
  starred?: boolean;
  isSystemGenerated?: boolean;
  systemPurpose?: SystemPurpose | null;
  isUnread?: boolean;
  source?: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface IMessage {
  id: string;
  conversationId: string;
  content: string;
  role: "user" | "assistant" | "system";
  status: "sending" | "sent" | "failed";
  createdAt: Date;
  updatedAt: Date;
  messageId?: string;
  fileIds?: string[];
  fileData?: FileData[];
  toolName?: string | null;
  toolCategory?: string | null;
  workflowId?: string | null;
  selectedWorkflow?: WorkflowData | null;
  selectedCalendarEvent?: SelectedCalendarEventData | null;
  tool_data?: ToolDataEntry[] | null;
  follow_up_actions?: string[] | null;
  image_data?: ImageData | null;
  memory_data?: MemoryData | null;
  todo_progress?: TodoProgressData | null;
  pinned?: boolean;
  isConvoSystemGenerated?: boolean;
  metadata?: Record<string, unknown>;
  optimistic?: boolean;
  replyToMessageId?: string | null;
  replyToMessageData?: {
    id: string;
    content: string;
    role: "user" | "assistant";
  } | null;
}

class DBEventEmitter extends EventEmitter {
  emitMessageUpserted(_message: IMessage) {}
  emitMessageDeleted(_messageId: string, _conversationId: string) {}
  emitMessagesSynced(_conversationId: string, _messages: IMessage[]) {}
  emitMessageIdReplaced(_oldId: string, _newMessage: IMessage) {}
  emitConversationAdded(_conversation: IConversation) {}
  emitConversationUpdated(_conversation: IConversation) {}
  emitConversationDeleted(_conversationId: string) {}
  emitConversationsDeletedBulk(_conversationIds: string[]) {}
}

export const dbEventEmitter = new DBEventEmitter();

class ChatDexieStub {
  public conversations: unknown;
  public messages: unknown;

  public getConversation(_id: string): Promise<IConversation | undefined> {
    return Promise.resolve(undefined);
  }
  public getAllConversations(): Promise<IConversation[]> {
    return Promise.resolve([]);
  }
  public putConversation(conversation: IConversation): Promise<string> {
    return Promise.resolve(conversation.id);
  }
  public putConversationsBulk(
    conversations: IConversation[],
  ): Promise<string[]> {
    return Promise.resolve(conversations.map((c) => c.id));
  }
  public getMessagesForConversation(
    _conversationId: string,
  ): Promise<IMessage[]> {
    return Promise.resolve([]);
  }
  public getAllMessages(): Promise<IMessage[]> {
    return Promise.resolve([]);
  }
  public getConversationIdsWithMessages(): Promise<string[]> {
    return Promise.resolve([]);
  }
  public putMessage(message: IMessage): Promise<string> {
    return Promise.resolve(message.id);
  }
  public putMessagesBulk(messages: IMessage[]): Promise<string[]> {
    return Promise.resolve(messages.map((m) => m.id));
  }
  public persistMessagePair(
    userMessage: IMessage | null,
    botMessage: IMessage | null,
  ): Promise<{ userMessage: IMessage | null; botMessage: IMessage | null }> {
    return Promise.resolve({ userMessage, botMessage });
  }
  public replaceMessage(
    _temporaryId: string,
    _message: IMessage,
  ): Promise<void> {
    return Promise.resolve();
  }
  public deleteConversationAndMessages(
    _conversationId: string,
  ): Promise<void> {
    return Promise.resolve();
  }
  public deleteConversationsAndMessagesBulk(
    _conversationIds: string[],
  ): Promise<void> {
    return Promise.resolve();
  }
  public updateMessageContent(
    _messageId: string,
    _content: string,
  ): Promise<void> {
    return Promise.resolve();
  }
  public updateMessage(
    _messageId: string,
    _updates: Partial<IMessage>,
  ): Promise<void> {
    return Promise.resolve();
  }
  public updateMessageStatus(
    _messageId: string,
    _status: IMessage["status"],
  ): Promise<void> {
    return Promise.resolve();
  }
  public replaceOptimisticMessage(
    _optimisticId: string,
    _backendId: string,
    _updatedData?: Partial<IMessage>,
  ): Promise<void> {
    return Promise.resolve();
  }
  public syncMessages(
    _conversationId: string,
    _messages: IMessage[],
  ): Promise<void> {
    return Promise.resolve();
  }
  public clearAll(): Promise<void> {
    return Promise.resolve();
  }
  public cleanupOrphanedOptimisticMessages(
    _maxAgeMinutes = 5,
  ): Promise<number> {
    return Promise.resolve(0);
  }
  public updateConversationFields(
    _conversationId: string,
    _updates: Partial<IConversation>,
  ): Promise<void> {
    return Promise.resolve();
  }
}

export const db = new ChatDexieStub();
