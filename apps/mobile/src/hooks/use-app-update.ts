import { useCallback, useEffect, useState } from "react";
import type { AppStateStatus } from "react-native";
import { AppState } from "react-native";

export interface AppUpdateState {
  isUpdateAvailable: boolean;
  isChecking: boolean;
  applyUpdate: () => void;
  dismissUpdate: () => void;
}

// expo-updates is not yet installed. This hook provides the correct interface
// and gracefully no-ops until expo-updates is added to the project.
// To enable: run `npx expo install expo-updates` and replace the stub below
// with:
//   import * as Updates from "expo-updates";

export function useAppUpdate(): AppUpdateState {
  const [isUpdateAvailable, setIsUpdateAvailable] = useState(false);
  const [isChecking, setIsChecking] = useState(false);

  const checkForUpdate = useCallback(async () => {
    // Stub: replace with Updates.checkForUpdateAsync() once expo-updates is installed
    setIsChecking(true);
    try {
      // No-op until expo-updates is available
    } finally {
      setIsChecking(false);
    }
  }, []);

  const applyUpdate = useCallback(() => {
    if (!isUpdateAvailable) return;
    // Stub: replace with Updates.reloadAsync() once expo-updates is installed
    setIsUpdateAvailable(false);
  }, [isUpdateAvailable]);

  const dismissUpdate = useCallback(() => {
    setIsUpdateAvailable(false);
  }, []);

  useEffect(() => {
    void checkForUpdate();

    const subscription = AppState.addEventListener(
      "change",
      (state: AppStateStatus) => {
        if (state === "active") {
          void checkForUpdate();
        }
      },
    );

    return () => {
      subscription.remove();
    };
  }, [checkForUpdate]);

  return { isUpdateAvailable, isChecking, applyUpdate, dismissUpdate };
}
