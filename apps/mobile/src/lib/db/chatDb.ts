import AsyncStorage from "@react-native-async-storage/async-storage";
import type { Message } from "@/features/chat/api/chat-api";
import type { Conversation } from "@/features/chat/types/index";

const MESSAGES_PREFIX = "@chat_messages_";
const CONVERSATIONS_KEY = "@chat_conversations";
const MAX_CONVERSATIONS = 50;
const MAX_MESSAGES_PER_CONVERSATION = 200;

interface MessagesEntry {
  messages: SerializedMessage[];
}

// Serialized form — Date fields are stored as ISO strings for JSON round-trip
interface SerializedMessage extends Omit<Message, "timestamp"> {
  timestamp: string;
}

function serializeMessage(msg: Message): SerializedMessage {
  return {
    ...msg,
    timestamp:
      msg.timestamp instanceof Date
        ? msg.timestamp.toISOString()
        : new Date(msg.timestamp).toISOString(),
  };
}

function deserializeMessage(raw: SerializedMessage): Message {
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
      const limited = messages.slice(-MAX_MESSAGES_PER_CONVERSATION);
      const entry: MessagesEntry = {
        messages: limited.map(serializeMessage),
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

  /**
   * Reads every persisted conversation's messages in a single multiGet call.
   * Used to eagerly hydrate the React Query cache at app launch so opening
   * any cached chat is instant (web parity with IndexedDB hydration).
   */
  getAllMessages: async (): Promise<Map<string, Message[]>> => {
    const result = new Map<string, Message[]>();
    try {
      const keys = await AsyncStorage.getAllKeys();
      const messageKeys = keys.filter((k) => k.startsWith(MESSAGES_PREFIX));
      if (messageKeys.length === 0) return result;

      const entries = await AsyncStorage.multiGet(messageKeys);
      for (const [key, raw] of entries) {
        if (!raw) continue;
        try {
          const entry = JSON.parse(raw) as MessagesEntry;
          const conversationId = key.slice(MESSAGES_PREFIX.length);
          result.set(conversationId, entry.messages.map(deserializeMessage));
        } catch {
          // Skip corrupt entries — next save overwrites them.
        }
      }
    } catch (error) {
      console.warn("[chatDb] Failed to get all messages:", error);
    }
    return result;
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
