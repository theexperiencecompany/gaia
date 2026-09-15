"use client";

/**
 * The signed-in user, owned by a single TanStack Query cache entry.
 *
 * `["current-user"]` is the one source of truth for everything `GET /user/me`
 * returns. `useFetchUser` (mounted once, in `GlobalAuth`) drives the fetch;
 * every other reader joins the same cache entry through `useCurrentUser`, and
 * every writer that receives a fresh server payload writes it back with
 * `setCurrentUser` / `patchCurrentUser`. There is deliberately no store
 * mirroring this data — instant paint across reloads comes from the query
 * cache persister (see `layouts/QueryProvider.tsx`), not a second copy.
 */

import { type QueryClient, useQuery } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

import { authApi, type UserInfo } from "@/features/auth/api/authApi";
import {
  type CurrentUser,
  toCurrentUser,
} from "@/features/auth/utils/toCurrentUser";

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

/**
 * Shape returned before the query has answered. Frozen module constant so the
 * reference is stable across renders — `useCurrentUser()` must not return a
 * fresh object every render or every consumer re-renders on every render.
 *
 * An empty `userId` is the "not known yet" signal, exactly as the pre-hydration
 * user store was: see `useIsSubscriptionStatusUnknown`.
 */
const UNKNOWN_USER: CurrentUser = Object.freeze({
  userId: "",
  name: "",
  email: "",
  profilePicture: "",
  timezone: undefined,
  onboarding: undefined,
  selected_model: undefined,
});

/** The raw query, for the few callers that need status/error, not just data. */
const useCurrentUserQuery = () =>
  useQuery({ ...currentUserQueryOptions, select: toCurrentUser });

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
 * The current user, or an all-empty record while the answer is unknown
 * (server render, hydration, cold cache, in-flight fetch, or signed out).
 */
export const useCurrentUser = (): CurrentUser => {
  const hydrated = useIsHydrated();
  const { data } = useCurrentUserQuery();
  return hydrated && data ? data : UNKNOWN_USER;
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

/** Replace the cached user with a full server payload. */
export const setCurrentUser = (
  queryClient: QueryClient,
  info: UserInfo,
): void => {
  queryClient.setQueryData(CURRENT_USER_QUERY_KEY, info);
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
