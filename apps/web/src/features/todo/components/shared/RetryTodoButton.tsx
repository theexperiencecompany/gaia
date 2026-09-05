"use client";

import { Button } from "@heroui/button";
import { RefreshIcon } from "@icons";
import type React from "react";
import { useRetryTodo } from "@/features/todo/hooks/useRetryTodo";

interface RetryTodoButtonProps {
  todoId: string;
}

/** Re-runs a failed GAIA todo. Rendered next to the failure reason. */
export const RetryTodoButton: React.FC<RetryTodoButtonProps> = ({ todoId }) => {
  const retryTodo = useRetryTodo();

  return (
    <Button
      size="sm"
      variant="flat"
      color="danger"
      radius="lg"
      startContent={<RefreshIcon className="size-3.5" />}
      isLoading={retryTodo.isPending}
      onPress={() => retryTodo.mutate(todoId)}
    >
      Retry
    </Button>
  );
};
