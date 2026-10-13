// @vitest-environment jsdom

import type { ApprovalRequestData } from "@shared/chat";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TypedToolDataEntry } from "@/config/registries/toolRegistry";
import { useApprovalDecisionWebSocket } from "@/features/chat/hooks/useApprovalDecisionWebSocket";
import type { IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

type WsHandler = (message: unknown) => void;

const harness = vi.hoisted(() => ({
  wsManager: {
    on: vi.fn<(type: string, handler: WsHandler) => void>(),
    off: vi.fn<(type: string, handler: WsHandler) => void>(),
  },
}));

vi.mock("@/lib/websocket/WebSocketManager", () => ({
  wsManager: harness.wsManager,
}));

vi.mock("@/lib/db/chatDb", () => ({
  db: { putMessage: vi.fn() },
}));

const card = (
  approval_id: string,
  status: ApprovalRequestData["status"] = "pending",
): TypedToolDataEntry => ({
  tool_name: "approval_request",
  tool_category: "hil",
  timestamp: "2026-09-19T00:00:00Z",
  data: {
    approval_id,
    tool_call_id: `call-${approval_id}`,
    gated_tool_name: "GMAIL_SEND_EMAIL",
    integration_name: "gmail",
    summary: `Send ${approval_id}`,
    args_preview: {},
    status,
    feedback: null,
    auto_reason: null,
    timeout_seconds: 300,
  },
});

const message = (id: string, tool_data: IMessage["tool_data"]): IMessage => ({
  id,
  conversationId: "conv-1",
  content: "hi",
  role: "assistant",
  status: "sent",
  createdAt: new Date(),
  updatedAt: new Date(),
  messageId: id,
  kind: null,
  reacts_to_message_id: null,
  tool_data: tool_data ?? null,
  follow_up_actions: null,
  replyToMessageData: null,
});

function handler(): WsHandler {
  expect(harness.wsManager.on).toHaveBeenCalledWith(
    "hil_approval_decided",
    expect.any(Function),
  );
  const call = harness.wsManager.on.mock.calls.find(
    ([t]) => t === "hil_approval_decided",
  );
  return call?.[1] as WsHandler;
}

describe("useApprovalDecisionWebSocket", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useChatStore.setState({
      messagesByConversation: {
        "conv-1": [
          message("m1", [
            card("ap_1"),
            card("ap_2"),
            card("ap_3"),
            card("ap_4"),
          ]),
        ],
      },
    });
    // Mount the subscription (hook body runs on import in test via direct call is
    // unavailable without a renderer; invoke through React in the shell below).
  });

  it("settles the matching card and leaves siblings alone", async () => {
    const { renderHook } = await import("@testing-library/react");
    renderHook(() => useApprovalDecisionWebSocket());
    await handler()({
      type: "hil_approval_decided",
      data: {
        conversation_id: "conv-1",
        approval_id: "ap_1",
        status: "approved",
        feedback: null,
        version: 1,
      },
    });
    const msgs = useChatStore.getState().messagesByConversation["conv-1"] ?? [];
    const entries = (msgs[0]?.tool_data ?? []) as {
      data: { approval_id: string; status: string };
    }[];
    expect(
      entries.find((e) => e.data.approval_id === "ap_1")?.data.status,
    ).toBe("approved");
    expect(
      entries.find((e) => e.data.approval_id === "ap_2")?.data.status,
    ).toBe("pending");
  });

  it("raises revoked tombstones and ignores unknown ids and statuses", async () => {
    const { renderHook } = await import("@testing-library/react");
    renderHook(() => useApprovalDecisionWebSocket());
    const h = handler();
    await h({
      type: "hil_approval_decided",
      data: {
        conversation_id: "conv-1",
        approval_id: "ap_2",
        status: "revoked",
        feedback: null,
        version: 2,
      },
    });
    await h({
      type: "hil_approval_decided",
      data: {
        conversation_id: "conv-1",
        approval_id: "ap_nope",
        status: "approved",
        feedback: null,
        version: 1,
      },
    });
    await h({
      type: "hil_approval_decided",
      data: {
        conversation_id: "conv-1",
        approval_id: "ap_1",
        status: "executing",
        feedback: null,
        version: 1,
      },
    });
    await h({
      type: "hil_approval_decided",
      data: {
        conversation_id: "conv-1",
        approval_id: "ap_3",
        status: "executed",
        feedback: null,
        version: 2,
      },
    });
    await h({
      type: "hil_approval_decided",
      data: {
        conversation_id: "conv-1",
        approval_id: "ap_4",
        status: "unknown",
        feedback: null,
        version: 3,
      },
    });
    const msgs = useChatStore.getState().messagesByConversation["conv-1"] ?? [];
    const entries = (msgs[0]?.tool_data ?? []) as {
      data: { approval_id: string; status: string };
    }[];
    expect(
      entries.find((e) => e.data.approval_id === "ap_2")?.data.status,
    ).toBe("revoked");
    expect(
      entries.find((e) => e.data.approval_id === "ap_1")?.data.status,
    ).toBe("pending");
    expect(
      entries.find((e) => e.data.approval_id === "ap_3")?.data.status,
    ).toBe("executed");
    expect(
      entries.find((e) => e.data.approval_id === "ap_4")?.data.status,
    ).toBe("unknown");
  });
});
