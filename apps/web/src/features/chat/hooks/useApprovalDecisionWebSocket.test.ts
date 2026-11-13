// @vitest-environment jsdom

import type { ApprovalRequestData } from "@shared/chat";
import {
  applyFrame,
  EMPTY_CONVERSATION_VIEW,
  type Entry,
} from "@shared/conversation";
import { useApprovalSettlementStore } from "@shared/conversation/live";
import { entryFrame, reply } from "@shared/conversation/testing";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useApprovalDecisionWebSocket } from "@/features/chat/hooks/useApprovalDecisionWebSocket";
import { liveMessages } from "@/features/chat/live/liveMessages";

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

const card = (approval_id: string) => ({
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
    outcome: null,
    feedback: null,
    auto_reason: null,
    timeout_seconds: 300,
  },
});

// A reply in the log carrying four approval cards, none decided in the log.
const VIEW = applyFrame(
  EMPTY_CONVERSATION_VIEW,
  entryFrame(1, {
    ...reply("r1", "a1", "Here are the emails to send."),
    tool_data: ["ap_1", "ap_2", "ap_3", "ap_4"].map(card),
  } as Entry),
).view;

const shown = (approvalId: string) =>
  (
    liveMessages(VIEW, {}, useApprovalSettlementStore.getState().settled)[0]
      ?.tool_data ?? []
  )
    .map((entry) => entry.data as ApprovalRequestData)
    .find((data) => data.approval_id === approvalId);

function handler(): WsHandler {
  const call = harness.wsManager.on.mock.calls.find(
    ([type]) => type === "hil_approval_decided",
  );
  expect(call).toBeDefined();
  return call?.[1] as WsHandler;
}

const decided = (
  approval_id: string,
  outcome: string,
  action: string | null = null,
  version = 1,
) => ({
  type: "hil_approval_decided",
  data: {
    conversation_id: "conv-1",
    approval_id,
    outcome,
    action,
    feedback: null,
    version,
  },
});

describe("useApprovalDecisionWebSocket", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useApprovalSettlementStore.setState({ settled: {} });
    renderHook(() => useApprovalDecisionWebSocket());
  });

  it("settles the matching card on screen and leaves siblings alone", () => {
    handler()(decided("ap_1", "approved"));

    expect(shown("ap_1")?.outcome).toBe("approved");
    expect(shown("ap_2")?.outcome).toBeNull();
  });

  it("raises withdrawn tombstones and ignores unknown ids and outcomes", () => {
    const h = handler();
    h(decided("ap_2", "withdrawn", null, 2));
    h(decided("ap_nope", "approved"));
    h(decided("ap_1", "executing"));
    h(decided("ap_3", "approved", "executed", 2));
    h(decided("ap_4", "approved", "unknown", 3));

    expect(shown("ap_2")?.outcome).toBe("withdrawn");
    expect(shown("ap_1")?.outcome).toBeNull();
    expect(shown("ap_3")?.action).toBe("executed");
    expect(shown("ap_4")?.action).toBe("unknown");
  });
});
