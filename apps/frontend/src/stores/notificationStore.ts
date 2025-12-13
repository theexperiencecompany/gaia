import { create } from "zustand";
import { devtools } from "zustand/middleware";

interface NotificationState {
  refreshTrigger: number;
}

interface NotificationActions {
  triggerRefresh: () => void;
}

type NotificationStore = NotificationState & NotificationActions;

const initialState: NotificationState = {
  refreshTrigger: 0,
};

export const useNotificationStore = create<NotificationStore>()(
  devtools(
    (set) => ({
      ...initialState,

      triggerRefresh: () =>
        set(
          (state) => ({ refreshTrigger: state.refreshTrigger + 1 }),
          false,
          "triggerRefresh",
        ),
    }),
    { name: "notification-store" },
  ),
);

// Selector for easy access
export const useRefreshTrigger = () =>
  useNotificationStore((state) => state.refreshTrigger);
