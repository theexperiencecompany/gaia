import { QueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

/** How many attempts a query worth retrying gets after the first failure. */
const MAX_QUERY_RETRIES = 2;

/**
 * A 4xx is the server's settled answer about this request; repeating it
 * cannot change it. It matters most for the paywall: a 402 re-runs the whole
 * gate, which mints another checkout session server-side and raises the wall
 * again client-side, so one blocked screen used to cost three rounds of that
 * per gated query.
 */
const shouldRetryQuery = (failureCount: number, error: Error): boolean => {
  const status = isAxiosError(error) ? error.response?.status : undefined;
  if (status !== undefined && status >= 400 && status < 500) return false;
  return failureCount < MAX_QUERY_RETRIES;
};

/**
 * The browser's single QueryClient.
 *
 * `QueryProvider` renders this instance, so non-React code (module-level
 * helpers that need cached server data, e.g. `getUserHomeTimezone`) can read
 * the same cache the components read instead of keeping a second copy of the
 * data in a store.
 *
 * On the server every render gets a fresh client — a module-level singleton
 * there would leak one request's data into the next.
 */
const queryClientOptions = {
  defaultOptions: {
    queries: {
      // With SSR, we usually want to set some default staleTime
      // above 0 to avoid refetching immediately on the client
      staleTime: 60 * 1000, // 1 minute (default for most queries)
      retry: shouldRetryQuery,
      refetchOnWindowFocus: false,
    },
  },
};

let browserQueryClient: QueryClient | undefined;

export const getQueryClient = (): QueryClient => {
  if (typeof window === "undefined") return new QueryClient(queryClientOptions);
  browserQueryClient ??= new QueryClient(queryClientOptions);
  return browserQueryClient;
};
