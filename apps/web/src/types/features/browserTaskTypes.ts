/**
 * Browser-automation card payloads streamed as `browser_task_data` tool_data.
 * Mirrors the BrowserCardSnapshot models in apps/api/app/schemas/browser.py
 * field for field: they ride the SSE stream, not a route, so the OpenAPI
 * export (and the generated types) never sees them. A field the model
 * defaults is optional here, as the generator would make it.
 */

import type {
  BrowserSessionStatus,
  HandoffStatus,
} from "@shared/api/generated";

export type { BrowserSessionStatus } from "@shared/api/generated";

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

export type { HandoffDecision as BrowserHandoffDecision } from "@shared/api/generated";

/**
 * Live-view WebSocket wire protocol. The API proxies these between the viewer
 * and the browser host: the host streams `frame` messages out; the viewer sends
 * CDP-shaped `mouse` / `key` messages and keyboard `text` back (only when
 * interactive).
 */

export interface BrowserFrameMessage {
  /** The icon the page itself declares — what the user's own browser tab shows. */
  favicon?: string | null;
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

/** A phone keyboard's committed text, inserted into the page as one edit. */
export interface BrowserTextMessage {
  type: "text";
  text: string;
}

export type BrowserLiveInputMessage =
  | BrowserMouseMessage
  | BrowserKeyMessage
  | BrowserTextMessage;
