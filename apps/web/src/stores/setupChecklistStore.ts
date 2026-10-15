import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

interface SetupChecklistState {
  /** Pending item keys the admin dismissed; each stays hidden while it is still pending. */
  dismissedKeys: string[];
  dismiss: (keys: string[]) => void;
  /** Forget dismissals of items that are no longer pending, so one that returns shows again. */
  keepPending: (pendingKeys: string[]) => void;
}

export const useSetupChecklistStore = create<SetupChecklistState>()(
  devtools(
    persist(
      (set) => ({
        dismissedKeys: [],
        dismiss: (keys) =>
          set(
            (state) => ({
              dismissedKeys: [...new Set([...state.dismissedKeys, ...keys])],
            }),
            false,
            "setupChecklist/dismiss",
          ),
        keepPending: (pendingKeys) =>
          set(
            (state) => {
              const pending = new Set(pendingKeys);
              const kept = state.dismissedKeys.filter((key) =>
                pending.has(key),
              );
              return kept.length === state.dismissedKeys.length
                ? state
                : { dismissedKeys: kept };
            },
            false,
            "setupChecklist/keepPending",
          ),
      }),
      {
        name: "gaia-setup-checklist",
        partialize: (state) => ({ dismissedKeys: state.dismissedKeys }),
      },
    ),
    { name: "setupChecklist-store" },
  ),
);
