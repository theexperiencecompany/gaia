import {
  type UseQueryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { calendarApi } from "../api/calendarApi";
import { calendarKeys } from "../api/queryKeys";

/** The user's selected calendar ids, as the server stores them. */
export const useCalendarPreferences = (
  options?: Partial<UseQueryOptions<string[], Error>>,
) =>
  useQuery({
    queryKey: calendarKeys.preferences,
    queryFn: calendarApi.fetchCalendarPreferences,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 1,
    refetchOnWindowFocus: false,
    ...options,
  });

/** Save a new calendar selection, showing it at once and rolling back when the server refuses it. */
export const useUpdateCalendarPreferences = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: calendarApi.updateCalendarPreferences,
    onMutate: async (selected: string[]) => {
      await queryClient.cancelQueries({ queryKey: calendarKeys.preferences });
      const previous = queryClient.getQueryData<string[]>(
        calendarKeys.preferences,
      );
      queryClient.setQueryData(calendarKeys.preferences, selected);
      return { previous };
    },
    onError: (_error, _selected, context) => {
      queryClient.setQueryData(calendarKeys.preferences, context?.previous);
    },
  });
};
