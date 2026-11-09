"use client";

import { Button } from "@heroui/button";
import { ArrowLeft01Icon } from "@icons";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useConversationRow } from "@/features/chat/hooks/useConversationList";

/**
 * In a tracked todo's chat, the way back to the todo. The chat is in no list,
 * so without this the only way out of it is the browser's back button.
 */
export function TodoChatBackLink() {
  const { id } = useParams<{ id?: string }>();
  const todoId = useConversationRow(id)?.todo_id;

  if (!todoId) return null;

  return (
    <Button
      as={Link}
      href={`/todos?todoId=${todoId}`}
      size="sm"
      variant="light"
      startContent={<ArrowLeft01Icon className="size-4" />}
    >
      Back to task
    </Button>
  );
}
