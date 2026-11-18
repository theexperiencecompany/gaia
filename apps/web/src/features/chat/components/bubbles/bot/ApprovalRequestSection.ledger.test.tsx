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
  description: {
    action: "Send an email",
    headline: 'Send an email to b@x: "Q3 numbers"',
    confirm: "send it",
    details: [
      { label: "To", value: "b@x" },
      { label: "Subject", value: '"Q3 numbers"' },
    ],
  },
  args_preview: { to: "b@x", thread_id: "th_42" },
  status: "waiting",
  outcome: null,
  feedback: null,
  auto_reason: null,
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

  it("leads with the server's headline and labelled details, raw arguments behind a tap", () => {
    render(
      <ApprovalRequestSection
        data={card({ auto_reason: "GAIA isn't sure you asked for this." })}
      />,
    );
    expect(
      screen.getByText('Send an email to b@x: "Q3 numbers"'),
    ).toBeDefined();
    expect(screen.getByText("Subject")).toBeDefined();
    expect(screen.getByText('"Q3 numbers"')).toBeDefined();
    expect(
      screen.getByText("GAIA isn't sure you asked for this."),
    ).toBeDefined();
    expect(screen.queryByText("th_42")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /show all details/i }));
    expect(screen.getByText("th_42")).toBeDefined();
  });

  it("shows every argument when the server has no labelled details", () => {
    render(
      <ApprovalRequestSection
        data={card({
          description: {
            action: "Run a tool",
            headline: "Run a tool",
            confirm: "do it",
            details: [],
          },
        })}
      />,
    );
    expect(screen.getByText("th_42")).toBeDefined();
    expect(
      screen.queryByRole("button", { name: /show all details/i }),
    ).toBeNull();
  });

  it("says the server's re-ask sentence on a card asked again after a yes with a change", () => {
    const question = "Updated subject to “Q4 numbers” — still OK to send it?";
    render(
      <ApprovalRequestSection
        data={card({
          description: {
            ...card().description,
            question,
            change_note: "Updated subject to “Q4 numbers”",
            changes: [{ label: "Subject", value: "“Q4 numbers”" }],
          },
        })}
      />,
    );
    expect(screen.getByText(question)).toBeDefined();
  });

  it("does not repeat the plain question on a first ask", () => {
    render(
      <ApprovalRequestSection
        data={card({
          description: {
            ...card().description,
            question: "OK to send an email to b@x?",
          },
        })}
      />,
    );
    expect(screen.queryByText("OK to send an email to b@x?")).toBeNull();
  });

  it("names the action it will stop asking about", () => {
    render(<ApprovalRequestSection data={card()} />);
    fireEvent.click(
      screen.getByRole("button", { name: /more approval options/i }),
    );
    expect(screen.getByText("Don't ask again to send an email")).toBeDefined();
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

  it("sends the note typed on the card with an approve, as the change to make", async () => {
    // Regression: the note was dropped on Approve, so the call ran as it stood.
    render(<ApprovalRequestSection data={card({ asked_at: askedAgo(5) })} />);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "  change the subject to Q4  " },
    });
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenCalledWith("ap_1", {
        decision: "approve",
        feedback: "change the subject to Q4",
        scope: "once",
      }),
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
