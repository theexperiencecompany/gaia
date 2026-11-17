"use client";

import { Comment01Icon } from "@icons";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { useOpenTodoChat } from "@/features/todo/hooks/useOpenTodoChat";

interface OpenTodoChatButtonProps {
  todoId: string;
}

/** Opens the tracked todo's own chat, where its runs execute and the user can follow up. */
export function OpenTodoChatButton({ todoId }: OpenTodoChatButtonProps) {
  const { openChat, isOpening } = useOpenTodoChat(todoId);

  return (
    <GaiaButton
      size="sm"
      variant="secondary"
      onPress={openChat}
      isPending={isOpening}
    >
      {isOpening ? null : <Comment01Icon className="size-4" />}
      Open chat
    </GaiaButton>
  );
}
