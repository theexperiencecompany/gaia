import { apiService } from "@/lib/api/service";
import type { FirstStepsResponse } from "@/types/features/firstStepsTypes";

export const firstStepsApi = {
  fetchFirstSteps: async (): Promise<FirstStepsResponse> => {
    return apiService.get<FirstStepsResponse>("/users/me/first-steps", {
      silent: true,
    });
  },

  // Response shape isn't part of the documented contract (only the effect —
  // marking the step complete server-side — is specified), so the caller
  // relies on an optimistic cache update rather than this return value.
  markFirstStep: async (step: string): Promise<void> => {
    await apiService.patch("/users/me/first-steps", { step }, { silent: true });
  },

  // Hides a single checklist row server-side (persists across browsers).
  hideFirstStep: async (step: string): Promise<void> => {
    await apiService.patch(
      "/users/me/first-steps/hide",
      { step },
      { silent: true },
    );
  },
};
