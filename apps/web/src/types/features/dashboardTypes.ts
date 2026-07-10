// Today view types — mirrors `GET /dashboard/today`
// (apps/api/app/services/dashboard_service.py): one sectioned payload,
// five saved searches over the todos collection.

import type { TodoAssignee } from "@shared/types";

export interface TodayNeedsYouItem {
  todo_id: string;
  title: string;
  serves: string | null;
  execution_status: "proposed" | "needs_you";
  blocker_question: string | null;
  conversation_id: string | null;
}

export interface TodaySuggestedItem {
  todo_id: string;
  title: string;
  serves: string | null;
  gaia_offer: string;
}

export interface TodayInFlightItem {
  todo_id: string;
  title: string;
  serves: string | null;
  execution_status: "queued" | "running";
  started_at: string | null;
  conversation_id: string | null;
}

export interface TodayYourTaskItem {
  todo_id: string;
  title: string;
  serves: string | null;
  due_at: string | null;
  gaia_offer: string | null;
}

export interface TodayDoneItem {
  todo_id: string;
  title: string;
  serves: string | null;
  completed_at: string | null;
  assignee: TodoAssignee;
  conversation_id: string | null;
}

export interface TodayNextEvent {
  time: string;
  title: string;
}

export interface TodaySubline {
  date: string;
  needs_you: number;
  next_event: TodayNextEvent | null;
}

export interface TodayRuns {
  used: number;
  limit: number;
  period: "day" | "month";
  reset_time: string;
}

export interface DashboardTodayResponse {
  headline: string;
  subline: TodaySubline;
  runs: TodayRuns | null;
  needs_you: TodayNeedsYouItem[];
  suggested: TodaySuggestedItem[];
  in_flight: TodayInFlightItem[];
  your_tasks: TodayYourTaskItem[];
  done_today: TodayDoneItem[];
}
