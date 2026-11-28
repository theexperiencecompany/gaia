"use client";

/**
 * The signed-in user, owned by a single TanStack Query cache entry.
 *
 * `["current-user"]` is the one source of truth for `GET /user/me`.
 * `useFetchUser` (mounted once in `GlobalAuth`) drives the fetch; every
 * other reader joins this cache via `useCurrentUser`, and writers patch it
 * back with `patchCurrentUser` — no store mirrors this data; instant paint
 * comes from the query cache persister (see `layouts/QueryProvider.tsx`).
 */

import { type Query, type QueryClient, useQuery } from "@tanstack/react-query";
import { createContext, useContext, useSyncExternalStore } from "react";

import { authApi, type UserInfo } from "@/features/auth/api/authApi";
import { hasSessionHint } from "@/features/auth/utils/sessionHint";

/** Identity of the current-user cache entry. Import it; never re-type it. */
export const CURRENT_USER_QUERY_KEY = ["current-user"] as const;

export const currentUserQueryOptions = {
  queryKey: CURRENT_USER_QUERY_KEY,
  queryFn: () => authApi.fetchUserInfo(),
  // Mutations write the server's response straight back into this cache entry,
  // so a session only ever needs one fetch.
  staleTime: Number.POSITIVE_INFINITY,
  retry: false, // auth failures shouldn't be retried
} as const;

type CurrentUserQuery = Query<
  UserInfo,
  Error,
  UserInfo,
  typeof CURRENT_USER_QUERY_KEY
>;

/**
 * True inside the marketing tree, where most visitors never signed in: there every
 * reader of the current user asks /me only when the browser may have a session.
 */
const SessionHintGateContext = createContext(false);
export const SessionHintGateProvider = SessionHintGateContext.Provider;

/**
 * Whether /me is worth asking: always in the app; on marketing pages only with the
 * API's signed-in hint, or a user cached before the API issued the hint.
 */
export const useMayHaveSession = (): ((query: CurrentUserQuery) => boolean) => {
  const gated = useContext(SessionHintGateContext);
  return (query) =>
    !gated || hasSessionHint() || query.state.data !== undefined;
};

/** The raw query, for the few callers that need status/error, not just data. */
const useCurrentUserQuery = () =>
  useQuery({
    ...currentUserQueryOptions,
    enabled: useMayHaveSession(),
  });

const noSubscription = () => () => {
  // Hydration state never changes after the first client render.
};
const clientSnapshot = () => true;
const serverSnapshot = () => false;

/**
 * The server never knows the user, but the client can: the persisted cache
 * entry is restored before a streamed subtree hydrates. Reading it during the
 * hydration render would paint a name the server HTML does not have, which
 * React rejects as a mismatch. This keeps the hydration render on the
 * server's answer and flips to the cached one right after, without an
 * effect-driven extra render.
 */
const useIsHydrated = (): boolean =>
  useSyncExternalStore(noSubscription, clientSnapshot, serverSnapshot);

/**
 * The current user, or undefined while the answer is unknown (server render,
 * hydration, cold cache, in-flight fetch, or signed out).
 */
export const useCurrentUser = (): UserInfo | undefined => {
  const hydrated = useIsHydrated();
  const { data } = useCurrentUserQuery();
  return hydrated ? data : undefined;
};

/**
 * Whether `dataUpdatedAt` comes from a fetch made in this page session. The
 * `["current-user"]` entry is replayed from the persisted cache on reload so
 * the shell paints signed-in immediately, and that replay keeps its original
 * timestamp: anything older than the page itself is a previous session's
 * answer, not the server's current one.
 */
const isFetchedThisSession = (
  dataUpdatedAt: number,
  pageLoadedAt: number = performance.timeOrigin,
): boolean => dataUpdatedAt >= pageLoadedAt;

/**
 * True once `GET /user/me` has answered in this page session. Anything that
 * must not act on a stale identity (the onboarding wizard reconciling its
 * browser draft against the account) waits for this instead of the first
 * paint.
 */
export const useCurrentUserIsFresh = (): boolean => {
  const hydrated = useIsHydrated();
  const { isSuccess, dataUpdatedAt } = useCurrentUserQuery();
  return hydrated && isSuccess && isFetchedThisSession(dataUpdatedAt);
};

/**
 * Merge a server-confirmed partial payload into the cached user. A no-op when
 * nothing is cached yet — there is no user to patch, and inventing one would
 * fabricate a half-empty record the server never sent.
 */
export const patchCurrentUser = (
  queryClient: QueryClient,
  patch: Partial<UserInfo>,
): void => {
  queryClient.setQueryData<UserInfo>(CURRENT_USER_QUERY_KEY, (previous) =>
    previous ? { ...previous, ...patch } : previous,
  );
};

/** Drop the cached user (logout, 401). Also drops it from the persisted cache. */
export const clearCurrentUser = (queryClient: QueryClient): void => {
  queryClient.removeQueries({ queryKey: CURRENT_USER_QUERY_KEY });
};
