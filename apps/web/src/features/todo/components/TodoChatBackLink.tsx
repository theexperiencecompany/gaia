"use client";

import { buttonVariants } from "@heroui/react";
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
    <Link
      role="button"
      href={`/todos?todoId=${todoId}`}
      className={buttonVariants({ size: "sm", variant: "ghost" })}
    >
      <ArrowLeft01Icon className="size-4" />
      Back to task
    </Link>
  );
}
