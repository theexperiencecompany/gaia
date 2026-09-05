"use client";

import { useMutation } from "@tanstack/react-query";
import axios from "axios";

import {
  type AnswerTodoResponse,
  answerTodo,
} from "@/features/todo/api/todoActionsApi";
import { toast } from "@/lib/toast";
import { useTodoStore } from "@/stores/todoStore";

/**
 * Answers a blocked (needs_you) GAIA todo, re-queuing its run with the reply.
 * See `useApproveTodo` for why success is an optimistic store patch instead of
 * a full list reload.
 *
 * 409 (already resumed / not blocked) surfaces the server's `detail` message.
 */
export function useAnswerTodo() {
  return useMutation<
    AnswerTodoResponse,
    unknown,
    { todoId: string; answer: string }
  >({
    mutationFn: ({ todoId, answer }) => answerTodo(todoId, answer),
    onSuccess: (data, { todoId }) => {
      useTodoStore.getState().updateTodoOptimistic(todoId, {
        execution_status: data.execution_status,
      });
    },
    onError: (error) => {
      if (axios.isAxiosError(error) && error.response?.status === 409) {
        const detail = (error.response.data as { detail?: string })?.detail;
        toast.error(detail || "This task isn't waiting on an answer.");
        return;
      }
      toast.error("Failed to send your answer.");
    },
  });
}
