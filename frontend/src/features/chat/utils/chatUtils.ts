import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import type { Dispatch, SetStateAction } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import type { MessageType } from "@/types/features/convoTypes";

export const fetchMessages = async (
  conversationId: string,
  setConvoMessages: Dispatch<SetStateAction<MessageType[]>>,
  router: AppRouterInstance | string[],
) => {
  try {
    if (!conversationId) return;
    const messages = await chatApi.fetchMessages(conversationId);
    if (messages && messages.length > 1) setConvoMessages(messages);
  } catch (e) {
    console.error("Failed to fetch messages:", e);
    router.push("/c");
  }
};

/**
 * Format tool name for display
 * Converts snake_case tool names to readable format with Title Case
 */
export const formatToolName = (toolName: string): string => {
  return toolName
    .toLowerCase() // First convert to lowercase
    .replace(/_/g, " ") // Replace underscores with spaces
    .replace(/\b\w/g, (char) => char.toUpperCase()) // Capitalize first letter of each word
    .replace(/\s+tool$/i, "") // Remove "Tool" suffix (case insensitive)
    .trim(); // Trim whitespace
};
