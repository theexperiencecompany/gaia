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

/** Delay before the single retry of a failed tool-result POST. */
const RESULT_RETRY_DELAY_MS = 500;

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

  // The tool already executed — its result MUST reach the backend or the
  // awaiting agent tool times out. Retry a transient POST failure once
  // before giving up, so a momentary network blip doesn't waste the work.
  try {
    await chatApi.postDesktopToolResult(result);
  } catch {
    await new Promise((resolve) => setTimeout(resolve, RESULT_RETRY_DELAY_MS));
    try {
      await chatApi.postDesktopToolResult(result);
    } catch (error) {
      console.error(
        "[desktopToolBridge] Failed to deliver tool result after retry:",
        error,
      );
    }
  }
}
