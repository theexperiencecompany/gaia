/**
 * Desktop tool bridge types — shared between the web renderer (which relays
 * requests) and the Electron desktop app (which executes them).
 *
 * The backend publishes a `desktop_tool_request` frame on the chat SSE
 * stream; the renderer hands it to the Electron main process over IPC and
 * POSTs the result back to `/api/v1/desktop/tool-result`.
 */

export const DESKTOP_TOOL_NAMES = [
  "screenshot",
  "read_clipboard",
  "write_clipboard",
  "open_app",
  "open_url",
  "list_windows",
] as const;

export type DesktopToolName = (typeof DESKTOP_TOOL_NAMES)[number];

export function isDesktopToolName(value: string): value is DesktopToolName {
  return (DESKTOP_TOOL_NAMES as readonly string[]).includes(value);
}

export interface DesktopToolRequest {
  request_id: string;
  /** Untrusted over the wire — the executor validates via isDesktopToolName. */
  tool: string;
  params: Record<string, unknown>;
  timeout_ms: number;
}

export interface DesktopToolResult {
  request_id: string;
  ok: boolean;
  data: Record<string, unknown> | null;
  error: string | null;
}

/** Payload of a successful `screenshot` action. */
export interface DesktopScreenshotData {
  /** PNG sized for model vision (long edge capped). */
  image_b64: string;
  /** Small JPEG for the chat UI card. */
  thumbnail_b64: string;
  width: number;
  height: number;
  source_width: number;
  source_height: number;
}

export interface DesktopWindowInfo {
  app: string;
  title: string;
}

/** Mirrors Electron's systemPreferences media access statuses. */
export type DesktopMediaAccessStatus =
  | "not-determined"
  | "granted"
  | "denied"
  | "restricted"
  | "unknown";

export interface DesktopPermissionStatus {
  microphone: DesktopMediaAccessStatus;
  screen: DesktopMediaAccessStatus;
}

export type DesktopPermissionPane = "microphone" | "screen";
