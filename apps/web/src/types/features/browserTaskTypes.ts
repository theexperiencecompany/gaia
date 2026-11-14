/**
 * Browser-automation card payloads streamed as `browser_task_data` tool_data, and
 * the live-view wire protocol. The card shapes live in the shared lib, where the
 * bot follower renders them too.
 */

export type { HandoffDecision as BrowserHandoffDecision } from "@shared/api/generated";
export type {
  BrowserAction,
  BrowserHandoffSnapshot,
  BrowserHandoffStatus,
  BrowserResultSnapshot,
  BrowserSensitiveCategory,
  BrowserSessionSnapshot,
  BrowserSessionStatus,
  BrowserStepSnapshot,
  BrowserTaskSnapshot,
} from "@shared/conversation/browser-cards";

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
