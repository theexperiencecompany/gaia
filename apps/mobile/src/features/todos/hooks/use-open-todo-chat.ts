import { useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { todoApi } from "../api/todo-api";

/**
 * Open a tracked todo's own chat, where its runs execute. The server creates
 * it on first open; it is never in the chat list, so this is the only way in.
 */
export function useOpenTodoChat(onOpening?: () => void) {
  const router = useRouter();
  const [openingTodoId, setOpeningTodoId] = useState<string | null>(null);

  const openChat = useCallback(
    async (todoId: string) => {
      setOpeningTodoId(todoId);
      try {
        const { conversation_id } = await todoApi.openTodoConversation(todoId);
        onOpening?.();
        router.push(`/c/${conversation_id}` as never);
      } finally {
        setOpeningTodoId(null);
      }
    },
    [onOpening, router],
  );

  return { openChat, openingTodoId };
}
