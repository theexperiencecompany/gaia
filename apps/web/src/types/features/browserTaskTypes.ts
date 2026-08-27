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
  /** Wall-clock spent reaching this step (LLM think + actions), from the API. */
  elapsed_ms?: number | null;
}

export interface BrowserHandoffSnapshot {
  kind: "handoff";
  handoff_id: string;
  category: BrowserSensitiveCategory;
  reason: string;
  session_id?: string | null;
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

/**
 * Live-view WebSocket wire protocol. The API proxies these between the viewer
 * and the browser host: the host streams `frame` messages out; the viewer sends
 * CDP-shaped `mouse` / `key` messages back (only when interactive).
 */

export interface BrowserFrameMessage {
  type: "frame";
  data: string; // base64-encoded JPEG
  url?: string | null;
  title?: string | null;
  /** Page CSS size the frame was captured at — the coordinate space CDP input
   * expects. The frame bitmap may be downscaled relative to this. */
  cssWidth?: number | null;
  cssHeight?: number | null;
}

export type BrowserMouseEvent =
  | "mouseMoved"
  | "mousePressed"
  | "mouseReleased"
  | "mouseWheel";

export interface BrowserMouseMessage {
  type: "mouse";
  event: BrowserMouseEvent;
  x: number;
  y: number;
  button?: "left" | "middle" | "right";
  buttons?: number;
  clickCount?: number;
  deltaX?: number;
  deltaY?: number;
  /** CDP modifier bitmask: Alt=1, Ctrl=2, Meta=4, Shift=8. */
  modifiers?: number;
}

export interface BrowserKeyMessage {
  type: "key";
  event: "keyDown" | "keyUp";
  key: string;
  code: string;
  text?: string;
  windowsVirtualKeyCode?: number;
  nativeVirtualKeyCode?: number;
  /** CDP modifier bitmask: Alt=1, Ctrl=2, Meta=4, Shift=8. */
  modifiers?: number;
}

export type BrowserLiveInputMessage = BrowserMouseMessage | BrowserKeyMessage;
