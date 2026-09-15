import { useSyncExternalStore } from "react";

// The origin never changes mid-session, so a no-op subscribe is enough — React
// only needs the snapshot to be stable between renders.
const noopUnsubscribe = (): void => {
  // Intentional no-op: there is no live source to subscribe to.
};
const subscribeToOrigin = (): (() => void) => noopUnsubscribe;

const getOriginSnapshot = (): string => window.location.origin;

// The server has no origin; the hydration render must agree with it.
const getServerOriginSnapshot = (): string => "";

/** `window.location.origin` on the client, `""` on the server and during hydration. */
export function useWindowOrigin(): string {
  return useSyncExternalStore(
    subscribeToOrigin,
    getOriginSnapshot,
    getServerOriginSnapshot,
  );
}
