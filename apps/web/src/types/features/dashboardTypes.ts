// Mission Control aggregation types.
// Mirrors the backend response shapes from `GET /dashboard/today` and
// `GET /dashboard/heatmap` — see apps/api/app/api/v1/endpoints/dashboard.py

import type { TodoAssignee } from "@shared/types";

export type DashboardItemType = "todo" | "event" | "execution";

export interface DashboardTodayItem {
  type: DashboardItemType;
  time: string | null;
  title: string;
  status?: string | null;
  assignee?: TodoAssignee;
  todo_id?: string;
  subtitle?: string | null;
}

export interface DashboardTodayResponse {
  items: DashboardTodayItem[];
}

export interface HeatmapDay {
  date: string;
  user_count: number;
  gaia_count: number;
}

export interface DashboardHeatmapResponse {
  days: HeatmapDay[];
  streak: number;
}
