import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { browserApi } from "../api/browserApi";
import type { BrowserTask } from "../types";

const browserTasksKey = ["browser-tasks"] as const;

export function useBrowserTasks() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: browserTasksKey,
    queryFn: () => browserApi.listTasks(),
  });

  const deleteTask = useMutation({
    mutationFn: (id: string) => browserApi.deleteTask(id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: browserTasksKey }),
  });

  return {
    tasks: (query.data ?? []) as BrowserTask[],
    isLoading: query.isLoading,
    error: query.error as Error | null,
    refetch: query.refetch,
    deleteTask: deleteTask.mutate,
    deletingId: deleteTask.isPending ? deleteTask.variables : null,
  };
}
