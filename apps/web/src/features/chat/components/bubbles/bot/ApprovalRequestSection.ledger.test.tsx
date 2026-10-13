// @vitest-environment jsdom

import type { ApprovalRequestData } from "@shared/chat";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "@/features/chat/api/chatApi";
import ApprovalRequestSection from "@/features/chat/components/bubbles/bot/ApprovalRequestSection";
import { toast } from "@/lib/toast";

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: { postApprovalDecision: vi.fn() },
}));

vi.mock("@/features/chat/hooks/useMarkApprovalDecided", () => ({
  useMarkApprovalDecided: () => vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn() },
}));

const noop = (): void => undefined;

const card = (
  overrides: Partial<ApprovalRequestData> = {},
): ApprovalRequestData => ({
  approval_id: "ap_1",
  tool_call_id: "call-1",
  gated_tool_name: "GMAIL_SEND_EMAIL",
  integration_name: "gmail",
  summary: "Send email",
  args_preview: { to: "b@x" },
  status: "pending",
  feedback: null,
  timeout_seconds: 300,
  ...overrides,
});

describe("ApprovalRequestSection ledger UX", () => {
  beforeEach(() => {
    vi.mocked(chatApi.postApprovalDecision)
      .mockReset()
      .mockResolvedValue({ success: true });
  });

  it("shows the card age when the ledger provides it", () => {
    render(
      <ApprovalRequestSection
        data={card({ age_seconds: 172800 })}
        onDecided={noop}
      />,
    );
    expect(screen.getByText("asked 2d ago")).toBeDefined();
  });

  it("asks in place before submitting a day-old approval", async () => {
    render(
      <ApprovalRequestSection
        data={card({ age_seconds: 259200 })}
        onDecided={noop}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    // Re-confirm appears; nothing submitted yet.
    expect(screen.getByText(/still want this/i)).toBeDefined();
    expect(chatApi.postApprovalDecision).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /yes, still/i }));
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenCalledTimes(1),
    );
  });

  it("submits immediately on approve tap — no waiting room", async () => {
    render(
      <ApprovalRequestSection
        data={card({ age_seconds: 5 })}
        onDecided={noop}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    // No "Sending your approval" interstitial, no cancel button.
    expect(screen.queryByText(/sending your approval/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /cancel/i })).toBeNull();
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenCalledTimes(1),
    );
  });

  it("submits the rendered row version with the decision", async () => {
    const onDecided = vi.fn();
    render(
      <ApprovalRequestSection
        data={card({ age_seconds: 5, ledger_version: 4 })}
        onDecided={onDecided}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenCalledWith("ap_1", {
        decision: "approve",
        feedback: undefined,
        scope: "once",
        v: 4,
      }),
    );
  });

  it("drops the version on the retry after a stale-v conflict", async () => {
    vi.mocked(chatApi.postApprovalDecision)
      .mockReset()
      .mockResolvedValueOnce({ success: false, status: "pending" })
      .mockResolvedValueOnce({ success: true });
    render(
      <ApprovalRequestSection
        data={card({ age_seconds: 5, ledger_version: 4 })}
        onDecided={noop}
      />,
    );
    // First tap carries the rendered version.
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenNthCalledWith(1, "ap_1", {
        decision: "approve",
        feedback: undefined,
        scope: "once",
        v: 4,
      }),
    );
    // The conflict toast means the card re-enabled (submitting reset).
    await vi.waitFor(() => expect(toast.error).toHaveBeenCalled());
    const approve = () => screen.getByRole("button", { name: /^approve$/i });
    await vi.waitFor(() =>
      expect(approve().hasAttribute("disabled")).toBe(false),
    );
    // The card stayed pending; the second tap omits v so the CAS decides.
    fireEvent.click(approve());
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenNthCalledWith(2, "ap_1", {
        decision: "approve",
        feedback: undefined,
        scope: "once",
        v: undefined,
      }),
    );
  });

  it("settles immediately on approve with no loading state", async () => {
    const onDecided = vi.fn();
    render(
      <ApprovalRequestSection
        data={card({ age_seconds: 5 })}
        onDecided={onDecided}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await vi.waitFor(() =>
      expect(onDecided).toHaveBeenCalledWith("approved", null),
    );
    // No spinner, no running row, no waiting room anywhere.
    expect(screen.queryByText(/running/i)).toBeNull();
  });
});
