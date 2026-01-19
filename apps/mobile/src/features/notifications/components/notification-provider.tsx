import type * as Notifications from "expo-notifications";
import { createContext, type ReactNode, useContext, useState } from "react";
import { useNotifications } from "@/features/notifications";

interface NotificationContextValue {
  expoPushToken: string | null;
  notification: Notifications.Notification | null;
  error: string | null;
  isRegistered: boolean;
  isLoading: boolean;
  setError: (error: string | null) => void;
}

const NotificationContext = createContext<NotificationContextValue | null>(
  null,
);

export function NotificationProvider({ children }: { children: ReactNode }) {
  const notificationData = useNotifications();
  const [localError, setLocalError] = useState<string | null>(null);

  const contextValue: NotificationContextValue = {
    ...notificationData,
    error: localError ?? notificationData.error,
    setError: setLocalError,
  };

  return (
    <NotificationContext.Provider value={contextValue}>
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotificationContext() {
  const ctx = useContext(NotificationContext);
  if (!ctx)
    throw new Error(
      "useNotificationContext must be used inside NotificationProvider",
    );
  return ctx;
}
