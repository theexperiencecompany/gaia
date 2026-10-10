import { useSyncExternalStore } from "react";

const APPLE_PLATFORM_RE = /(Mac|iPhone|iPod|iPad)/i;

// Platform never changes mid-session, so a no-op subscribe is enough — React
// only needs the snapshot to be stable between renders.
const noopUnsubscribe = (): void => {
  // Intentional no-op: there is no live source to subscribe to.
};
const subscribeToPlatform = (): (() => void) => noopUnsubscribe;

function getPlatformSnapshot(): boolean {
  return APPLE_PLATFORM_RE.test(navigator.platform);
}

// Render-safe server/hydration default, matching the previous useState(true).
const getServerPlatformSnapshot = (): boolean => true;

export function usePlatform() {
  const isMac = useSyncExternalStore(
    subscribeToPlatform,
    getPlatformSnapshot,
    getServerPlatformSnapshot,
  );

  return {
    isMac,
    isWindows: !isMac,
    modifierKeyName: (isMac ? "command" : "ctrl") as "command" | "ctrl",
  };
}
