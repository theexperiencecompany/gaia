import { apiService } from "@/lib/api/service";
import type { DashboardTodayResponse } from "@/types/features/dashboardTypes";

export const dashboardApi = {
  // The Today view: headline + five status-grouped todo sections + runs quota.
  fetchToday: async (): Promise<DashboardTodayResponse> => {
    return apiService.get<DashboardTodayResponse>("/dashboard/today", {
      silent: true,
    });
  },
};
