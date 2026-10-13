import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

interface NotificationBannerState {
  isDismissed: boolean;
  dismiss: () => void;
}

export const useNotificationBannerStore = create<NotificationBannerState>()(
  devtools(
    persist(
      (set) => ({
        isDismissed: false,
        dismiss: () =>
          set({ isDismissed: true }, false, "notificationBanner/dismiss"),
      }),
      {
        name: "gaia-notification-connect-banner",
        partialize: (state) => ({ isDismissed: state.isDismissed }),
      },
    ),
    { name: "notificationBanner-store" },
  ),
);
