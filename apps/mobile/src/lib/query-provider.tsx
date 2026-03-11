import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { AppState, type AppStateStatus } from "react-native";

export const queryKeys = {
  conversations: ["chat", "conversations"] as const,
  todos: ["todos"] as const,
  workflows: ["workflows"] as const,
  integrations: ["integrations"] as const,
  notifications: ["notifications"] as const,
  models: ["models", "list"] as const,
};

const STALE_TIMES = {
  conversations: 30 * 1000,
  todos: 60 * 1000,
  workflows: 60 * 1000,
  integrations: 5 * 60 * 1000,
  notifications: 30 * 1000,
  models: 10 * 60 * 1000,
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000,
      gcTime: 5 * 60 * 1000,
      retry: 3,
      retryDelay: (attemptIndex) =>
        Math.min(1000 * 2 ** attemptIndex, 30000),
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
    },
  },
});

function setQueryStaleOverrides() {
  const overrides: Array<{
    queryKey: readonly string[];
    staleTime: number;
  }> = [
    { queryKey: queryKeys.conversations, staleTime: STALE_TIMES.conversations },
    { queryKey: queryKeys.todos, staleTime: STALE_TIMES.todos },
    { queryKey: queryKeys.workflows, staleTime: STALE_TIMES.workflows },
    {
      queryKey: queryKeys.integrations,
      staleTime: STALE_TIMES.integrations,
    },
    {
      queryKey: queryKeys.notifications,
      staleTime: STALE_TIMES.notifications,
    },
    { queryKey: queryKeys.models, staleTime: STALE_TIMES.models },
  ];

  for (const { queryKey, staleTime } of overrides) {
    queryClient.setQueryDefaults(queryKey, { staleTime });
  }
}

setQueryStaleOverrides();

interface QueryProviderProps {
  children: ReactNode;
}

export function QueryProvider({ children }: QueryProviderProps) {
  useEffect(() => {
    const subscription = AppState.addEventListener(
      "change",
      (nextState: AppStateStatus) => {
        if (nextState === "active") {
          queryClient.invalidateQueries();
        }
      },
    );

    return () => {
      subscription.remove();
    };
  }, []);

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

export { queryClient };
