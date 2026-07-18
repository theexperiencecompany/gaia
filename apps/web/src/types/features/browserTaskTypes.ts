/**
 * Browser-automation card payloads streamed as `browser_task_data` tool_data.
 * Mirrors apps/api/app/schemas/browser.py — the frontend folds the accumulated
 * array of snapshots into one live card.
 */

export type BrowserSessionStatus =
  | "starting"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type BrowserHandoffStatus =
  | "pending"
  | "completed"
  | "cancelled"
  | "timeout";

export type BrowserSensitiveCategory =
  | "none"
  | "payment"
  | "credentials"
  | "irreversible";

export interface BrowserSessionSnapshot {
  kind: "session";
  task: string;
  status: BrowserSessionStatus;
  session_id?: string | null;
  live_view_url?: string | null;
  detail?: string | null;
}

export interface BrowserStepSnapshot {
  kind: "step";
  index: number;
  goal: string;
  action?: string | null;
  url?: string | null;
  title?: string | null;
  screenshot?: string | null;
}

export interface BrowserHandoffSnapshot {
  kind: "handoff";
  handoff_id: string;
  category: BrowserSensitiveCategory;
  reason: string;
  live_view_url?: string | null;
  status: BrowserHandoffStatus;
}

export interface BrowserResultSnapshot {
  kind: "result";
  status: BrowserSessionStatus;
  success: boolean;
  summary: string;
  steps: number;
}

export type BrowserTaskSnapshot =
  | BrowserSessionSnapshot
  | BrowserStepSnapshot
  | BrowserHandoffSnapshot
  | BrowserResultSnapshot;

export type BrowserHandoffDecision = "continue" | "cancel";
