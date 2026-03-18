import AsyncStorage from "@react-native-async-storage/async-storage";
import type { Message } from "@/features/chat/api/chat-api";
import type { Conversation } from "@/features/chat/types/index";

const MESSAGES_PREFIX = "@chat_messages_";
const CONVERSATIONS_KEY = "@chat_conversations";
const MAX_CONVERSATIONS = 50;

interface MessagesEntry {
  messages: Message[];
  timestamp: number;
}

function serializeMessage(msg: Message): Message {
  return {
    ...msg,
    timestamp:
      msg.timestamp instanceof Date ? msg.timestamp : new Date(msg.timestamp),
  };
}

function deserializeMessage(raw: Message): Message {
  return {
    ...raw,
    timestamp: new Date(raw.timestamp),
  };
}

export const chatDb = {
  saveMessages: async (
    conversationId: string,
    messages: Message[],
  ): Promise<void> => {
    try {
      const entry: MessagesEntry = {
        messages: messages.map(serializeMessage),
        timestamp: Date.now(),
      };
      await AsyncStorage.setItem(
        `${MESSAGES_PREFIX}${conversationId}`,
        JSON.stringify(entry),
      );
    } catch (error) {
      console.warn("[chatDb] Failed to save messages:", error);
    }
  },

  getMessages: async (conversationId: string): Promise<Message[]> => {
    try {
      const raw = await AsyncStorage.getItem(
        `${MESSAGES_PREFIX}${conversationId}`,
      );
      if (!raw) return [];
      const entry = JSON.parse(raw) as MessagesEntry;
      return entry.messages.map(deserializeMessage);
    } catch (error) {
      console.warn("[chatDb] Failed to get messages:", error);
      return [];
    }
  },

  saveConversations: async (conversations: Conversation[]): Promise<void> => {
    try {
      const limited = conversations.slice(0, MAX_CONVERSATIONS);
      await AsyncStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(limited));
    } catch (error) {
      console.warn("[chatDb] Failed to save conversations:", error);
    }
  },

  getConversations: async (): Promise<Conversation[]> => {
    try {
      const raw = await AsyncStorage.getItem(CONVERSATIONS_KEY);
      return raw ? (JSON.parse(raw) as Conversation[]) : [];
    } catch (error) {
      console.warn("[chatDb] Failed to get conversations:", error);
      return [];
    }
  },

  deleteConversation: async (id: string): Promise<void> => {
    try {
      await AsyncStorage.removeItem(`${MESSAGES_PREFIX}${id}`);
    } catch (error) {
      console.warn("[chatDb] Failed to delete conversation cache:", error);
    }
  },

  clearAll: async (): Promise<void> => {
    try {
      const keys = await AsyncStorage.getAllKeys();
      const chatKeys = keys.filter(
        (k) => k.startsWith(MESSAGES_PREFIX) || k === CONVERSATIONS_KEY,
      );
      if (chatKeys.length > 0) {
        await AsyncStorage.multiRemove(chatKeys);
      }
    } catch (error) {
      console.warn("[chatDb] Failed to clear chat cache:", error);
    }
  },
};
