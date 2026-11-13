import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

interface UpdatesSeenState {
  lastSeenAt: string | null;
  markSeen: () => void;
  startCounting: () => void;
}

export const useUpdatesSeenStore = create<UpdatesSeenState>()(
  devtools(
    persist(
      (set, get) => ({
        lastSeenAt: null,
        markSeen: () =>
          set({ lastSeenAt: new Date().toISOString() }, false, "updates/seen"),
        // First run counts from now, so an existing feed does not read as new.
        startCounting: () => {
          if (get().lastSeenAt === null) get().markSeen();
        },
      }),
      {
        name: "gaia-updates-seen",
        partialize: (state) => ({ lastSeenAt: state.lastSeenAt }),
      },
    ),
    { name: "updatesSeen-store" },
  ),
);
