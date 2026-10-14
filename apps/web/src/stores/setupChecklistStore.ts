import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

interface SetupChecklistState {
  /** Item keys that were pending when the checklist was last dismissed. */
  dismissedKeys: string[];
  dismiss: (keys: string[]) => void;
}

export const useSetupChecklistStore = create<SetupChecklistState>()(
  devtools(
    persist(
      (set) => ({
        dismissedKeys: [],
        dismiss: (keys) =>
          set({ dismissedKeys: keys }, false, "setupChecklist/dismiss"),
      }),
      {
        name: "gaia-setup-checklist",
        partialize: (state) => ({ dismissedKeys: state.dismissedKeys }),
      },
    ),
    { name: "setupChecklist-store" },
  ),
);
