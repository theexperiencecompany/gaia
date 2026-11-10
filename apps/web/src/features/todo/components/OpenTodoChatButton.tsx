"use client";

import { Button } from "@heroui/button";
import { Comment01Icon } from "@icons";
import { useOpenTodoChat } from "@/features/todo/hooks/useOpenTodoChat";

interface OpenTodoChatButtonProps {
  todoId: string;
}

/** Opens the tracked todo's own chat, where its runs execute and the user can follow up. */
export function OpenTodoChatButton({ todoId }: OpenTodoChatButtonProps) {
  const { openChat, isOpening } = useOpenTodoChat(todoId);

  return (
    <Button
      size="sm"
      variant="flat"
      onPress={openChat}
      isLoading={isOpening}
      startContent={isOpening ? null : <Comment01Icon className="size-4" />}
    >
      Open chat
    </Button>
  );
}
