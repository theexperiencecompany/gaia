/**
 * Desktop tool dispatcher — the privileged half of the desktop tool bridge.
 *
 * The renderer relays `desktop_tool_request` frames from the chat SSE
 * stream here over IPC; this module routes each action to its handler and
 * returns a serializable result the renderer POSTs back to the backend.
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

export async function dispatchDesktopTool(
  request: DesktopToolRequest,
): Promise<DesktopToolResult> {
  try {
    const data = await executeAction(request);
    return { request_id: request.request_id, ok: true, data, error: null };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[Main] Desktop tool '${request.tool}' failed:`, message);
    return {
      request_id: request.request_id,
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
    throw new Error(`Missing required string parameter '${key}'`);
  }
  return value;
}
