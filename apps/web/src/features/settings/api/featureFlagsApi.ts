import { api } from "@/lib/api/typed";

// Toasts come from the API layer (skipped when the app shell already handled
// the failure, e.g. the paywall); the hook only rolls the switch back.
export const featureFlagsApi = {
  list: () =>
    api.get("/api/v1/features", {
      errorMessage: "Failed to load experimental features",
    }),

  setEnabled: (flag: string, enabled: boolean) =>
    api.patch("/api/v1/features/{flag}", {
      path: { flag },
      body: { enabled },
      errorMessage: "Failed to update experimental feature",
    }),
};
