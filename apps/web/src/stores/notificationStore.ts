import { create } from "zustand";
import { devtools } from "zustand/middleware";

import type { NotificationRecord } from "@/types/features/notificationTypes";

interface NotificationState {
  notifications: NotificationRecord[];
  isLoaded: boolean;
  isFetching: boolean;
}

interface NotificationActions {
  setNotifications: (notifications: NotificationRecord[]) => void;
  addNotification: (notification: NotificationRecord) => void;
  updateNotification: (notification: NotificationRecord) => void;
  setFetching: (isFetching: boolean) => void;
}

type NotificationStore = NotificationState & NotificationActions;

const initialState: NotificationState = {
  notifications: [],
  isLoaded: false,
  isFetching: false,
};

export const useNotificationStore = create<NotificationStore>()(
  devtools(
    (set) => ({
      ...initialState,

      setNotifications: (notifications) =>
        set({ notifications, isLoaded: true }, false, "setNotifications"),

      addNotification: (notification) =>
        set(
          (state) => {
            if (state.notifications.some((n) => n.id === notification.id)) {
              return state;
            }
            return { notifications: [notification, ...state.notifications] };
          },
          false,
          "addNotification",
        ),

      updateNotification: (updatedNotification) =>
        set(
          (state) => ({
            notifications: state.notifications.map((n) =>
              n.id === updatedNotification.id ? updatedNotification : n,
            ),
          }),
          false,
          "updateNotification",
        ),

      setFetching: (isFetching) => set({ isFetching }, false, "setFetching"),
    }),
    { name: "notification-store" },
  ),
);
