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

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn() },
}));

const card = (
  overrides: Partial<ApprovalRequestData> = {},
): ApprovalRequestData => ({
  approval_id: "ap_1",
  tool_call_id: "call-1",
  gated_tool_name: "GMAIL_SEND_EMAIL",
  integration_name: "gmail",
  summary: "Send email",
  args_preview: { to: "b@x" },
  outcome: null,
  feedback: null,
  auto_reason: null,
  timeout_seconds: 300,
  ...overrides,
});

const askedAgo = (seconds: number): string =>
  new Date(Date.now() - seconds * 1000).toISOString();

describe("ApprovalRequestSection ledger UX", () => {
  beforeEach(() => {
    vi.mocked(chatApi.postApprovalDecision)
      .mockReset()
      .mockResolvedValue({ success: true });
  });

  it("shows how long ago the card was asked", () => {
    render(
      <ApprovalRequestSection data={card({ asked_at: askedAgo(172800) })} />,
    );
    expect(screen.getByText("asked 2d ago")).toBeDefined();
  });

  it("asks in place before submitting a day-old approval", async () => {
    render(
      <ApprovalRequestSection data={card({ asked_at: askedAgo(259200) })} />,
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
    render(<ApprovalRequestSection data={card({ asked_at: askedAgo(5) })} />);
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    // No "Sending your approval" interstitial, no cancel button.
    expect(screen.queryByText(/sending your approval/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /cancel/i })).toBeNull();
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenCalledTimes(1),
    );
  });

  it("says an already-decided approval was decided and re-enables the card", async () => {
    vi.mocked(chatApi.postApprovalDecision)
      .mockReset()
      .mockResolvedValueOnce({ success: false, outcome: null });
    render(<ApprovalRequestSection data={card({ asked_at: askedAgo(5) })} />);
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenCalledWith("ap_1", {
        decision: "approve",
        feedback: undefined,
        scope: "once",
      }),
    );
    await vi.waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "That approval was already decided",
      ),
    );
    await vi.waitFor(() =>
      expect(
        screen
          .getByRole("button", { name: /^approve$/i })
          .hasAttribute("disabled"),
      ).toBe(false),
    );
  });
});

describe("ApprovalRequestSection always-allow menu", () => {
  it("offers always-allow on a card the user can waive", () => {
    render(<ApprovalRequestSection data={card()} />);
    expect(
      screen.getByRole("button", { name: /more approval options/i }),
    ).toBeDefined();
  });

  it("hides always-allow on a card that asks every time", () => {
    render(<ApprovalRequestSection data={card({ always_asks: true })} />);
    expect(
      screen.queryByRole("button", { name: /more approval options/i }),
    ).toBeNull();
  });
});
