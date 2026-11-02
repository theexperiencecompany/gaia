import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { todoApi } from "@/features/todo/api/todoApi";

/**
 * Open a tracked todo's own chat: where its runs execute, live and past. The
 * server creates the chat on first open; it is never in the chat list, so this
 * is the only way in. A failure surfaces as the API layer's toast.
 */
export function useOpenTodoChat(todoId: string) {
  const router = useRouter();
  const [isOpening, setIsOpening] = useState(false);

  const openChat = useCallback(async () => {
    setIsOpening(true);
    try {
      const { conversation_id } = await todoApi.openTodoConversation(todoId);
      router.push(`/c/${conversation_id}`);
    } finally {
      setIsOpening(false);
    }
  }, [router, todoId]);

  return { openChat, isOpening };
}
