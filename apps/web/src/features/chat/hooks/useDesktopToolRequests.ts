"use client";

import type {
  DesktopToolRequest,
  DesktopToolResult,
} from "@shared/desktop-tools";
import { useEffect } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { getElectronAPI } from "@/lib/electron/api";
import { wsManager } from "@/lib/websocket/WebSocketManager";

export const DESKTOP_TOOL_REQUEST = "desktop_tool_request";

/** Delay before the single retry of a failed tool-result POST. */
const RESULT_RETRY_DELAY_MS = 500;

interface DesktopToolRequestMessage {
  type: typeof DESKTOP_TOOL_REQUEST;
  request: DesktopToolRequest;
}

async function runOnDesktop(
  request: DesktopToolRequest,
): Promise<DesktopToolResult> {
  const electronApi = getElectronAPI();
  if (!electronApi) {
    throw new Error("desktop tool request relayed outside the desktop app");
  }
  try {
    return await electronApi.executeDesktopTool(request);
  } catch (error) {
    return {
      request_id: request.request_id,
      ok: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/** Run one pushed request on this desktop and post its result; the awaiting agent tool resumes on that post. */
export async function relayDesktopToolRequest(
  request: DesktopToolRequest,
): Promise<void> {
  const result = await runOnDesktop(request);
  // The action already ran, so a transient POST failure gets one retry before the tool times out.
  try {
    await chatApi.postDesktopToolResult(result);
  } catch {
    await new Promise((resolve) => setTimeout(resolve, RESULT_RETRY_DELAY_MS));
    await chatApi.postDesktopToolResult(result);
  }
}

/** In the desktop app, answer the agent's desktop tool requests pushed over the user's WebSocket. */
export function useDesktopToolRequests(): void {
  useEffect(() => {
    if (!getElectronAPI()) return;
    const handler = (message: unknown) => {
      const { request } = message as DesktopToolRequestMessage;
      relayDesktopToolRequest(request).catch((error: unknown) => {
        console.error(
          "[desktop tools] Result never reached the server:",
          error,
        );
      });
    };
    wsManager.on(DESKTOP_TOOL_REQUEST, handler);
    return () => wsManager.off(DESKTOP_TOOL_REQUEST, handler);
  }, []);
}
