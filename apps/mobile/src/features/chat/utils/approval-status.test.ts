import type { ApprovalRequestData, ApprovalStatus } from "@gaia/shared/chat";
import { describe, expect, it } from "vitest";
import type { Message } from "@/features/chat/api/chat-api";
import {
  APPROVAL_CHIP_META,
  APPROVAL_RESOLVED_META,
  applyApprovalDecisionToMessages,
  approvalOutcomeText,
} from "./approval-status";

function card(
  approval_id: string,
  status: ApprovalStatus = "pending",
): {
  tool_name: string;
  data: ApprovalRequestData;
} {
  return {
    tool_name: "approval_request",
    data: {
      approval_id,
      tool_call_id: `call-${approval_id}`,
      gated_tool_name: "send_email",
      integration_name: "gmail",
      summary: `Send ${approval_id}`,
      args_preview: {},
      status,
      feedback: null,
      timeout_seconds: 300,
    },
  };
}

function msg(
  id: string,
  toolData: { tool_name: string; data: unknown }[],
): Message {
  return {
    id,
    text: "hi",
    isUser: false,
    timestamp: new Date("2026-09-19T00:00:00Z"),
    toolData: toolData as Message["toolData"],
  };
}

describe("APPROVAL_RESOLVED_META — ledger-terminal crash guard", () => {
  it("covers every non-pending status so the card never derefs undefined", () => {
    const statuses: Exclude<ApprovalStatus, "pending">[] = [
      "approved",
      "denied",
      "timeout",
      "abandoned",
      "auto_approved",
      "revoked",
      "executed",
      "failed",
      "unknown",
    ];
    for (const status of statuses) {
      expect(APPROVAL_RESOLVED_META[status]).toBeDefined();
      expect(APPROVAL_RESOLVED_META[status].label.length).toBeGreaterThan(0);
    }
  });

  it("matches web SubagentRow chip labels for ledger states", () => {
    expect(APPROVAL_RESOLVED_META.executed.label).toBe("Executed");
    expect(APPROVAL_RESOLVED_META.failed.label).toBe("Failed");
    expect(APPROVAL_RESOLVED_META.unknown.label).toBe("Unknown");
  });
});

describe("APPROVAL_CHIP_META — activity row chips", () => {
  it("renders a chip for every ledger-terminal state instead of null", () => {
    expect(APPROVAL_CHIP_META.executed.label).toBe("Executed");
    expect(APPROVAL_CHIP_META.failed.label).toBe("Failed");
    expect(APPROVAL_CHIP_META.unknown.label).toBe("Unknown");
    expect(APPROVAL_CHIP_META.revoked.label.length).toBeGreaterThan(0);
    expect(APPROVAL_CHIP_META.approved.label).toBe("Approved");
  });
});

describe("approvalOutcomeText — libs fallback", () => {
  const base: ApprovalRequestData = {
    approval_id: "ap_1",
    tool_call_id: "call-1",
    gated_tool_name: "send_email",
    integration_name: "gmail",
    summary: "Send email",
    args_preview: {},
    status: "pending",
    feedback: null,
    timeout_seconds: 300,
  };

  it.each(["executed", "failed", "unknown"] as const)(
    "returns a non-empty line for %s (shared returns '')",
    (status) => {
      const text = approvalOutcomeText({ ...base, status });
      expect(text.trim().length).toBeGreaterThan(0);
    },
  );

  it("prefers explicit feedback when present", () => {
    const text = approvalOutcomeText({
      ...base,
      status: "executed",
      feedback: "Sent message abc",
    });
    expect(text).toContain("Sent message abc");
  });
});

describe("applyApprovalDecisionToMessages — hil_approval_decided settle", () => {
  it("flips the matching card and leaves siblings alone", () => {
    const messages = [
      msg("m1", [card("ap_1"), card("ap_2")]),
      msg("m2", [card("ap_3")]),
    ];
    const { messages: next, changed } = applyApprovalDecisionToMessages(
      messages,
      {
        conversation_id: "conv-1",
        approval_id: "ap_1",
        status: "approved",
        feedback: null,
      },
    );
    expect(changed).toBe(true);
    const statuses = (next[0].toolData ?? []).map(
      (e) => (e.data as ApprovalRequestData).status,
    );
    expect(statuses).toEqual(["approved", "pending"]);
    const siblingEntries = next[1].toolData ?? [];
    expect((siblingEntries[0].data as ApprovalRequestData).status).toBe(
      "pending",
    );
  });

  it.each(["revoked", "executed", "failed", "unknown"] as const)(
    "settles ledger-terminal status %s",
    (status) => {
      const { messages: next, changed } = applyApprovalDecisionToMessages(
        [msg("m1", [card("ap_1")])],
        {
          conversation_id: "conv-1",
          approval_id: "ap_1",
          status,
          feedback: status === "failed" ? "tool exploded" : null,
        },
      );
      expect(changed).toBe(true);
      const data = next[0].toolData?.[0].data as ApprovalRequestData;
      expect(data.status).toBe(status);
    },
  );

  it("is a no-op for unknown ids and never mutates the input", () => {
    const messages = [msg("m1", [card("ap_1")])];
    const { messages: next, changed } = applyApprovalDecisionToMessages(
      messages,
      {
        conversation_id: "conv-1",
        approval_id: "ap_nope",
        status: "approved",
        feedback: null,
      },
    );
    expect(changed).toBe(false);
    expect(next).toBe(messages);
  });
});
