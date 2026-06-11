/**
 * Renderer half of the desktop tool bridge.
 *
 * When the chat SSE stream carries a `desktop_tool_request` frame, this
 * relays it to the Electron main process for execution and POSTs the result
 * back to the backend, where the awaiting agent tool picks it up.
 */

import type {
  DesktopToolRequest,
  DesktopToolResult,
} from "@shared/desktop-tools";
import { chatApi } from "@/features/chat/api/chatApi";
import { getElectronAPI } from "@/lib/electron/api";

export async function relayDesktopToolRequest(
  request: DesktopToolRequest,
): Promise<void> {
  const electronApi = getElectronAPI();
  // Outside the desktop app there is nothing to execute — the backend's
  // timeout answers the request. (Desktop tools shouldn't surface here
  // anyway; this guards mixed-client edge cases.)
  if (!electronApi) return;

  let result: DesktopToolResult;
  try {
    result = await electronApi.executeDesktopTool(request);
  } catch (error) {
    result = {
      request_id: request.request_id,
      ok: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }

  try {
    await chatApi.postDesktopToolResult(result);
  } catch (error) {
    console.error("[desktopToolBridge] Failed to deliver tool result:", error);
  }
}
