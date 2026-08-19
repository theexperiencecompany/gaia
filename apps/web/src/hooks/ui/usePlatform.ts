import { useSyncExternalStore } from "react";

export function usePlatform() {
  const mounted = useSyncExternalStore(
    () => () => undefined,
    () => true,
    () => false,
  );
  const isMac = mounted
    ? /(Mac|iPhone|iPod|iPad)/i.test(navigator.platform)
    : true;

  return {
    isMac,
    isWindows: !isMac,
    modifierKeyName: (isMac ? "command" : "ctrl") as "command" | "ctrl",
  };
}
