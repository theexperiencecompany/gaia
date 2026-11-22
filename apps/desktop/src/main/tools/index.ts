/**
 * Desktop tool dispatcher — the privileged half of the desktop tool bridge.
 *
 * The renderer relays `desktop_tool_request` messages from the user's
 * WebSocket here over IPC; this module routes each action to its handler and
 * returns a serializable result the renderer POSTs back to the backend.
 * Every window of the app receives the same message, so one request id runs
 * once: later relays share the first run's result.
 *
 * @module tools
 */

import type {
  DesktopToolRequest,
  DesktopToolResult,
} from "@gaia/shared/desktop-tools";
import { isDesktopToolName } from "@gaia/shared/desktop-tools";
import { listWindows, openApp, openUrl } from "./apps";
import { readClipboardText, writeClipboardText } from "./clipboard";
import { captureScreenshot } from "./screenshot";

const runs = new Map<string, Promise<DesktopToolResult>>();

export function dispatchDesktopTool(
  request: DesktopToolRequest,
): Promise<DesktopToolResult> {
  const requestId =
    typeof request?.request_id === "string" ? request.request_id : "";
  const running = runs.get(requestId);
  if (running) return running;
  const run = runDesktopTool(request, requestId);
  if (requestId) {
    runs.set(requestId, run);
    void run.finally(() => runs.delete(requestId));
  }
  return run;
}

async function runDesktopTool(
  request: DesktopToolRequest,
  requestId: string,
): Promise<DesktopToolResult> {
  // request arrives from the wire — read identity defensively so a malformed
  // frame still yields a serializable result instead of throwing past it.
  const toolName = typeof request?.tool === "string" ? request.tool : "unknown";
  try {
    const data = await executeAction(request);
    return { request_id: requestId, ok: true, data, error: null };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[Main] Desktop tool '${toolName}' failed:`, message);
    return {
      request_id: requestId,
      ok: false,
      data: null,
      error: message,
    };
  }
}

async function executeAction(
  request: DesktopToolRequest,
): Promise<Record<string, unknown>> {
  // request.tool is untrusted over the wire — validate against the known
  // tool names before routing, as the DesktopToolRequest contract documents.
  if (!isDesktopToolName(request.tool)) {
    throw new Error(`Unsupported desktop tool: ${request.tool}`);
  }

  const params = request.params ?? {};

  switch (request.tool) {
    case "screenshot":
      return { ...(await captureScreenshot()) };
    case "read_clipboard":
      return { ...readClipboardText() };
    case "write_clipboard":
      writeClipboardText(requireStringParam(params, "text"));
      return {};
    case "open_app":
      await openApp(requireStringParam(params, "app_name"));
      return {};
    case "open_url":
      await openUrl(requireStringParam(params, "url"));
      return {};
    case "list_windows":
      return { ...(await listWindows()) };
    default:
      throw new Error(`Unsupported desktop tool: ${request.tool}`);
  }
}

function requireStringParam(
  params: Record<string, unknown>,
  key: string,
): string {
  const value = params[key];
  if (typeof value !== "string") {
    throw new TypeError(`Missing required string parameter '${key}'`);
  }
  return value;
}
