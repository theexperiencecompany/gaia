// @vitest-environment jsdom

import type { ApprovalRequestData } from "@shared/chat";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "@/features/chat/api/chatApi";
import ApprovalRequestSection from "@/features/chat/components/bubbles/bot/ApprovalRequestSection";
import { toast } from "@/lib/toast";

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: { postApprovalDecision: vi.fn() },
}));

const markDecided = vi.fn();
vi.mock("@/features/chat/hooks/useMarkApprovalDecided", () => ({
  useMarkApprovalDecided: () => markDecided,
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const noop = (): void => undefined;
const NOW = new Date("2026-11-12T10:00:00Z");
const askedAgo = (seconds: number): string =>
  new Date(NOW.getTime() - seconds * 1000).toISOString();

const card = (
  overrides: Partial<ApprovalRequestData> = {},
): ApprovalRequestData =>
  ({
    approval_id: "ap_1",
    tool_call_id: "call-1",
    gated_tool_name: "GMAIL_SEND_EMAIL",
    integration_name: "Gmail",
    summary: 'Send an email to bob@x.com: "Q3 numbers"',
    description: {
      action: "Send an email",
      headline: 'Send an email to bob@x.com: "Q3 numbers"',
      confirm: "send it",
      details: [
        { label: "To", value: "bob@x.com" },
        { label: "Subject", value: "Q3 numbers" },
      ],
    },
    args_preview: { recipient_email: "bob@x.com", subject: "Q3 numbers" },
    status: "pending",
    feedback: null,
    auto_reason: null,
    asked_at: askedAgo(5),
    ...overrides,
  }) as ApprovalRequestData;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  markDecided.mockReset();
  vi.mocked(toast.success).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ApprovalRequestSection ledger UX", () => {
  beforeEach(() => {
    vi.mocked(chatApi.postApprovalDecision)
      .mockReset()
      .mockResolvedValue({ success: true });
  });

  it("computes the card age from when it was asked, at render time", () => {
    render(
      <ApprovalRequestSection
        data={card({ asked_at: askedAgo(172800) })}
        onDecided={noop}
      />,
    );
    expect(screen.getByText("Asked 2d ago")).toBeDefined();
  });

  it("asks in place, once, before submitting a day-old approval", async () => {
    render(
      <ApprovalRequestSection
        data={card({ asked_at: askedAgo(172800) })}
        onDecided={noop}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    // Regression: the template appended a second "ago" ("Asked 2d ago ago").
    expect(screen.getByText("Asked 2d ago — still want this?")).toBeDefined();
    expect(chatApi.postApprovalDecision).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /yes, still/i }));
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenCalledTimes(1),
    );
  });

  it("submits immediately on approve tap — no waiting room", async () => {
    render(<ApprovalRequestSection data={card()} onDecided={noop} />);
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    expect(screen.queryByText(/sending your approval/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /cancel/i })).toBeNull();
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenCalledTimes(1),
    );
  });

  it("says what GAIA does next once the user approves", async () => {
    render(<ApprovalRequestSection data={card()} onDecided={noop} />);
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await vi.waitFor(() =>
      expect(markDecided).toHaveBeenCalledWith(
        undefined,
        "Carrying on: send an email",
      ),
    );
  });

  it("submits the rendered row version with the decision", async () => {
    render(
      <ApprovalRequestSection
        data={card({ ledger_version: 4 })}
        onDecided={noop}
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
        data={card({ ledger_version: 4 })}
        onDecided={noop}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenNthCalledWith(1, "ap_1", {
        decision: "approve",
        feedback: undefined,
        scope: "once",
        v: 4,
      }),
    );
    await vi.waitFor(() => expect(toast.error).toHaveBeenCalled());
    const approve = () => screen.getByRole("button", { name: /^approve$/i });
    await vi.waitFor(() =>
      expect(approve().hasAttribute("disabled")).toBe(false),
    );
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
    render(<ApprovalRequestSection data={card()} onDecided={onDecided} />);
    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await vi.waitFor(() =>
      expect(onDecided).toHaveBeenCalledWith("approved", null),
    );
    expect(screen.queryByText(/running/i)).toBeNull();
  });
});

describe("ApprovalRequestSection reads as a sentence", () => {
  it("leads with the plain-language action and its labelled facts, not the tool slug", () => {
    render(<ApprovalRequestSection data={card()} onDecided={noop} />);
    expect(
      screen.getByText('Send an email to bob@x.com: "Q3 numbers"'),
    ).toBeDefined();
    expect(screen.getByText("To")).toBeDefined();
    expect(screen.getByText("Subject")).toBeDefined();
    expect(screen.queryByText(/gmail send email/i)).toBeNull();
    // Raw argument keys stay behind "Show all details".
    expect(screen.queryByText("Recipient email")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show all details" }));
    expect(screen.getByText("Recipient email")).toBeDefined();
  });

  it("names the integration the action runs in", () => {
    render(<ApprovalRequestSection data={card()} onDecided={noop} />);
    expect(screen.getByText("in Gmail", { exact: false })).toBeDefined();
  });

  it("shows why auto mode is checking", () => {
    render(
      <ApprovalRequestSection
        data={card({
          auto_reason:
            "GAIA isn't sure you asked for this, so it's checking with you first.",
        })}
        onDecided={noop}
      />,
    );
    expect(
      screen.getByText(
        "GAIA isn't sure you asked for this, so it's checking with you first.",
      ),
    ).toBeDefined();
  });

  it("reads a card saved before descriptions from its summary", () => {
    render(
      <ApprovalRequestSection
        data={card({ description: undefined, summary: "Gmail send email" })}
        onDecided={noop}
      />,
    );
    expect(screen.getByText("Gmail send email")).toBeDefined();
  });
});

describe("ApprovalRequestSection always-allow menu", () => {
  beforeEach(() => {
    vi.mocked(chatApi.postApprovalDecision)
      .mockReset()
      .mockResolvedValue({ success: true });
  });

  it("names what it stops asking about and confirms the setting changed", async () => {
    render(<ApprovalRequestSection data={card()} onDecided={noop} />);
    fireEvent.click(
      screen.getByRole("button", { name: /more approval options/i }),
    );
    fireEvent.click(
      await screen.findByText("Don't ask again to send an email"),
    );
    await vi.waitFor(() =>
      expect(chatApi.postApprovalDecision).toHaveBeenCalledWith(
        "ap_1",
        expect.objectContaining({ decision: "approve", scope: "always_tool" }),
      ),
    );
    await vi.waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "GAIA won't ask about this again",
        {
          description:
            "It will send an email without checking. Turn asking back on in that integration's Permissions.",
        },
      ),
    );
  });

  it("hides always-allow on a card that asks every time", () => {
    render(
      <ApprovalRequestSection
        data={card({ always_asks: true })}
        onDecided={noop}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /more approval options/i }),
    ).toBeNull();
  });
});
