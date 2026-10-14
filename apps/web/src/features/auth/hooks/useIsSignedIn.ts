import { useSyncExternalStore } from "react";

import { useUserStore } from "@/stores/userStore";

const emptySubscribe = () => () => {
  /* no-op unsubscribe for server snapshot */
};
const getClientSnapshot = () => true;
const getServerSnapshot = () => false;

/**
 * Whether a user is signed in, safe to render on public, server-rendered pages.
 *
 * The user store is persisted in localStorage and rehydrates synchronously on
 * the client, so reading it directly would render a different tree on the
 * first client render than the server sent (a hydration mismatch).
 * `useSyncExternalStore` keeps the server/hydration snapshot false and flips to
 * true on the client without an effect-driven extra render.
 */
export function useIsSignedIn(): boolean {
  const email = useUserStore((state) => state.email);
  const mounted = useSyncExternalStore(
    emptySubscribe,
    getClientSnapshot,
    getServerSnapshot,
  );
  return mounted && Boolean(email);
}
