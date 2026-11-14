import type { ScreenItem } from "@gaia/shared/conversation";
import AsyncStorage from "@react-native-async-storage/async-storage";
import type { Conversation } from "@/features/chat/types/index";

// v4: a conversation is the server's screen. Older caches are dropped once and refetched.
const LOG_PREFIX = "@chat_screen_v4_";
const RETIRED_MESSAGE_PREFIX = "@chat_messages_";
const CONVERSATIONS_KEY = "@chat_conversations";
const MAX_CONVERSATIONS = 50;

/** A conversation's screen as this device last saw it, its head, and where an older page starts. */
export interface SavedLog {
  items: ScreenItem[];
  head: number;
  olderBefore: number | null;
}

export const chatDb = {
  saveLog: async (conversationId: string, log: SavedLog): Promise<void> => {
    try {
      await AsyncStorage.setItem(
        `${LOG_PREFIX}${conversationId}`,
        JSON.stringify(log),
      );
    } catch (error) {
      console.warn("[chatDb] Failed to save the log:", error);
    }
  },

  getLog: async (conversationId: string): Promise<SavedLog | null> => {
    try {
      const raw = await AsyncStorage.getItem(`${LOG_PREFIX}${conversationId}`);
      return raw ? (JSON.parse(raw) as SavedLog) : null;
    } catch (error) {
      console.warn("[chatDb] Failed to read the log:", error);
      return null;
    }
  },

  /** Drop the message caches older builds saved; each conversation refetches its newest page once. */
  dropRetiredMessages: async (): Promise<void> => {
    try {
      const keys = await AsyncStorage.getAllKeys();
      const retired = keys.filter((k) => k.startsWith(RETIRED_MESSAGE_PREFIX));
      if (retired.length > 0) await AsyncStorage.multiRemove(retired);
    } catch (error) {
      console.warn("[chatDb] Failed to drop retired message caches:", error);
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
      await AsyncStorage.removeItem(`${LOG_PREFIX}${id}`);
    } catch (error) {
      console.warn("[chatDb] Failed to delete conversation cache:", error);
    }
  },

  clearAll: async (): Promise<void> => {
    try {
      const keys = await AsyncStorage.getAllKeys();
      const chatKeys = keys.filter(
        (k) => k.startsWith(LOG_PREFIX) || k === CONVERSATIONS_KEY,
      );
      if (chatKeys.length > 0) {
        await AsyncStorage.multiRemove(chatKeys);
      }
    } catch (error) {
      console.warn("[chatDb] Failed to clear chat cache:", error);
    }
  },
};
