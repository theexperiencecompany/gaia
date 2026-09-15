import { apiService } from "@/lib/api/service";
import type { FirstStepsResponse } from "@/types/features/firstStepsTypes";

export const firstStepsApi = {
  // Every `done` flag is derived server-side; there is no endpoint to set one.
  fetch: (): Promise<FirstStepsResponse> =>
    apiService.get<FirstStepsResponse>("/user/first-steps", { silent: true }),

  // Both directions persist, so a checklist expanded on one device stays
  // expanded on the next.
  setCollapsed: (collapsed: boolean): Promise<FirstStepsResponse> =>
    apiService.post<FirstStepsResponse>(
      "/user/first-steps/collapse",
      { collapsed },
      { silent: true },
    ),
};
