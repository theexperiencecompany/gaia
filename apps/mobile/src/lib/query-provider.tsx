import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useEffect } from "react";
import { AppState, type AppStateStatus } from "react-native";

export const queryKeys = {
  conversations: ["chat", "conversations"] as const,
  messages: ["chat", "messages"] as const,
  todos: ["todos"] as const,
  workflows: ["workflows"] as const,
  integrations: ["integrations"] as const,
  notifications: ["notifications"] as const,
  models: ["models", "list"] as const,
  skills: ["skills"] as const,
  tools: ["tools"] as const,
};

const STALE_TIMES = {
  conversations: 30 * 1000,
  messages: 10 * 1000,
  todos: 60 * 1000,
  workflows: 60 * 1000,
  integrations: 2 * 60 * 1000,
  notifications: 30 * 1000,
  models: 10 * 60 * 1000,
  staticData: 30 * 60 * 1000,
};

const CACHE_TIMES = {
  conversations: 5 * 60 * 1000,
  messages: 2 * 60 * 1000,
  todos: 10 * 60 * 1000,
  workflows: 10 * 60 * 1000,
  integrations: 30 * 60 * 1000,
  notifications: 5 * 60 * 1000,
  models: 30 * 60 * 1000,
  staticData: 60 * 60 * 1000,
};

interface ApiError {
  status?: number;
}

function isApiError(err: unknown): err is ApiError {
  return typeof err === "object" && err !== null && "status" in err;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000,
      gcTime: 5 * 60 * 1000,
      retry: (failureCount, error) => {
        if (isApiError(error) && error.status !== undefined) {
          if (error.status >= 400 && error.status < 500) {
            return false;
          }
        }
        return failureCount < 2;
      },
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
      refetchOnMount: true,
    },
  },
});

function setQueryStaleOverrides() {
  queryClient.setQueryDefaults(queryKeys.conversations, {
    staleTime: STALE_TIMES.conversations,
    gcTime: CACHE_TIMES.conversations,
  });

  queryClient.setQueryDefaults(queryKeys.messages, {
    staleTime: STALE_TIMES.messages,
    gcTime: CACHE_TIMES.messages,
  });

  queryClient.setQueryDefaults(queryKeys.todos, {
    staleTime: STALE_TIMES.todos,
    gcTime: CACHE_TIMES.todos,
  });

  queryClient.setQueryDefaults(queryKeys.workflows, {
    staleTime: STALE_TIMES.workflows,
    gcTime: CACHE_TIMES.workflows,
  });

  queryClient.setQueryDefaults(queryKeys.integrations, {
    staleTime: STALE_TIMES.integrations,
    gcTime: CACHE_TIMES.integrations,
  });

  queryClient.setQueryDefaults(queryKeys.notifications, {
    staleTime: STALE_TIMES.notifications,
    gcTime: CACHE_TIMES.notifications,
  });

  queryClient.setQueryDefaults(queryKeys.models, {
    staleTime: STALE_TIMES.models,
    gcTime: CACHE_TIMES.models,
  });

  queryClient.setQueryDefaults(queryKeys.skills, {
    staleTime: STALE_TIMES.staticData,
    gcTime: CACHE_TIMES.staticData,
  });

  queryClient.setQueryDefaults(queryKeys.tools, {
    staleTime: STALE_TIMES.staticData,
    gcTime: CACHE_TIMES.staticData,
  });
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
