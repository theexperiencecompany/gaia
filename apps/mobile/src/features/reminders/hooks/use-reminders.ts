import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  Reminder,
  ReminderCreate,
  ReminderUpdate,
} from "../api/reminders-api";
import { remindersApi } from "../api/reminders-api";

const REMINDERS_KEY = ["reminders"] as const;

export function useReminders() {
  const queryClient = useQueryClient();

  const {
    data: reminders = [],
    isLoading,
    isRefetching,
    error,
    refetch,
  } = useQuery<Reminder[], Error>({
    queryKey: REMINDERS_KEY,
    queryFn: remindersApi.getReminders,
  });

  const createMutation = useMutation<Reminder, Error, ReminderCreate>({
    mutationFn: remindersApi.createReminder,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: REMINDERS_KEY });
    },
  });

  const updateMutation = useMutation<
    Reminder,
    Error,
    { id: string; data: ReminderUpdate }
  >({
    mutationFn: ({ id, data }) => remindersApi.updateReminder(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: REMINDERS_KEY });
    },
  });

  const deleteMutation = useMutation<void, Error, string>({
    mutationFn: remindersApi.deleteReminder,
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: REMINDERS_KEY });
      const previous = queryClient.getQueryData<Reminder[]>(REMINDERS_KEY);
      queryClient.setQueryData<Reminder[]>(
        REMINDERS_KEY,
        (old) => old?.filter((r) => r.id !== id) ?? [],
      );
      return { previous };
    },
    onError: (_err, _id, context) => {
      const ctx = context as { previous?: Reminder[] } | undefined;
      if (ctx?.previous) {
        queryClient.setQueryData<Reminder[]>(REMINDERS_KEY, ctx.previous);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: REMINDERS_KEY });
    },
  });

  const pauseMutation = useMutation<Reminder, Error, string>({
    mutationFn: remindersApi.pauseReminder,
    onSuccess: (updated) => {
      queryClient.setQueryData<Reminder[]>(
        REMINDERS_KEY,
        (old) => old?.map((r) => (r.id === updated.id ? updated : r)) ?? [],
      );
    },
  });

  const resumeMutation = useMutation<Reminder, Error, string>({
    mutationFn: remindersApi.resumeReminder,
    onSuccess: (updated) => {
      queryClient.setQueryData<Reminder[]>(
        REMINDERS_KEY,
        (old) => old?.map((r) => (r.id === updated.id ? updated : r)) ?? [],
      );
    },
  });

  const activeReminders = reminders.filter((r) => r.status === "active");
  const pausedReminders = reminders.filter((r) => r.status === "paused");

  return {
    reminders,
    activeReminders,
    pausedReminders,
    isLoading,
    isRefreshing: isRefetching,
    error: error?.message ?? null,
    refetch,
    createReminder: createMutation.mutateAsync,
    updateReminder: (id: string, data: ReminderUpdate) =>
      updateMutation.mutateAsync({ id, data }),
    deleteReminder: deleteMutation.mutateAsync,
    pauseReminder: pauseMutation.mutateAsync,
    resumeReminder: resumeMutation.mutateAsync,
    isCreating: createMutation.isPending,
  };
}
