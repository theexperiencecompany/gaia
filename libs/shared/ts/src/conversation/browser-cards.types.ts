/**
 * Browser-automation card payloads, carried as `browser_task_data` tool_data on a
 * work item. Mirrors the BrowserCardSnapshot models in apps/api/app/schemas/browser.py
 * field for field: they ride the events stream inside a card, not a route, so the
 * OpenAPI export (and the generated types) never sees them. A field the model
 * defaults is optional here, as the generator would make it.
 */

import type { BrowserSessionStatus, HandoffStatus } from "../api/generated";

export type { BrowserSessionStatus } from "../api/generated";

export type BrowserHandoffStatus = HandoffStatus;

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
  detail?: string | null;
}

/** One action the browser agent invoked — its own tool call. */
export interface BrowserAction {
  name: string;
  inputs?: Record<string, unknown>;
  /** On-page text of the element this action targeted, resolved from the DOM. */
  target?: string | null;
}

export interface BrowserStepSnapshot {
  kind: "step";
  index: number;
  goal: string;
  /** Mirrored into the chat's tool thread, not rendered in the step row. */
  actions?: BrowserAction[];
  url?: string | null;
  title?: string | null;
  screenshot?: string | null;
  /** Wall-clock spent reaching this step (LLM think + actions), from the API. */
  elapsed_ms?: number | null;
  /** Equal for two steps exactly when they show the same frame. */
  frame_digest?: string | null;
}

export interface BrowserHandoffSnapshot {
  kind: "handoff";
  handoff_id: string;
  category?: BrowserSensitiveCategory;
  reason: string;
  session_id?: string | null;
  status: BrowserHandoffStatus;
  /** A sign-in finished here is kept for the next task (false when persistence is off). */
  saves_login?: boolean;
  /** The one-time link a chat-platform user takes the browser over with; null on a web run. */
  live_view_url?: string | null;
}

export interface BrowserResultSnapshot {
  kind: "result";
  status: BrowserSessionStatus;
  success: boolean;
  summary: string;
  steps?: number;
  replay_url?: string | null;
  user_notes?: string[];
}

export type BrowserTaskSnapshot =
  | BrowserSessionSnapshot
  | BrowserStepSnapshot
  | BrowserHandoffSnapshot
  | BrowserResultSnapshot;
