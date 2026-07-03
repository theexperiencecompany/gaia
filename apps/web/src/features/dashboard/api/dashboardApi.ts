import { apiService } from "@/lib/api/service";
import type {
  DashboardHeatmapResponse,
  DashboardTodayResponse,
} from "@/types/features/dashboardTypes";

export const dashboardApi = {
  // Today's timeline: todos + calendar events + workflow executions, chronological.
  fetchToday: async (): Promise<DashboardTodayResponse> => {
    return apiService.get<DashboardTodayResponse>("/dashboard/today", {
      silent: true,
    });
  },

  // Contribution grid + streak, derived from completed todos.
  fetchHeatmap: async (days = 365): Promise<DashboardHeatmapResponse> => {
    return apiService.get<DashboardHeatmapResponse>(
      `/dashboard/heatmap?days=${days}`,
      { silent: true },
    );
  },
};
