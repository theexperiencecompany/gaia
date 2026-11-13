import { describe, expect, it } from "vitest";
import type { ApprovalRequestData } from "../../chat";
import { formatApprovalPrompt } from "./approvalPrompt";
import { PLATFORM_MARKDOWN } from "./formatters";

const NOW = Date.parse("2026-11-12T10:00:00Z");

function card(
  overrides: Partial<ApprovalRequestData> = {},
): ApprovalRequestData {
  return {
    approval_id: "ap_1",
    tool_call_id: "call-1",
    gated_tool_name: "GMAIL_SEND_EMAIL",
    integration_name: "Gmail",
    summary: 'Send an email to bob@x.com, jane@y.com: "Q3 numbers"',
    description: {
      action: "Send an email",
      headline: 'Send an email to bob@x.com, jane@y.com: "Q3 numbers"',
      confirm: "send it",
      details: [
        { label: "To", value: "bob@x.com, jane@y.com" },
        { label: "Subject", value: "Q3 numbers" },
        {
          label: "Message",
          value: '"Hi both, attaching the Q3 numbers before Friday\'s…"',
        },
      ],
    },
    args_preview: {},
    status: "pending",
    feedback: null,
    auto_reason: null,
    asked_at: "2026-11-12T10:00:00Z",
    ...overrides,
  } as ApprovalRequestData;
}

describe("formatApprovalPrompt", () => {
  it("asks about one action in plain words, with its facts and the real verb", () => {
    expect(formatApprovalPrompt([card()], NOW)).toBe(
      [
        "GAIA wants to send an email",
        "To: bob@x.com, jane@y.com",
        "Subject: Q3 numbers",
        '"Hi both, attaching the Q3 numbers before Friday\'s…"'.replace(
          /^/,
          "Message: ",
        ),
        "",
        "Reply yes to send it, or no to cancel.",
      ].join("\n"),
    );
  });

  it("never names a tool slug or a raw field", () => {
    const prompt = formatApprovalPrompt([card()], NOW);
    expect(prompt).not.toContain("GMAIL_SEND_EMAIL");
    expect(prompt).not.toContain("recipient_email");
  });

  it("says nothing about expiry for an approval that never expires", () => {
    expect(formatApprovalPrompt([card()], NOW)).not.toMatch(/expire/i);
  });

  it("states an expiry only when the approval really has one", () => {
    const expiring = card({ expires_at: "2026-11-12T16:00:00Z" });
    expect(formatApprovalPrompt([expiring], NOW)).toContain(
      "If you don't answer, this expires in 6 hours.",
    );
  });

  it("says how long ago a stale approval was asked", () => {
    const stale = card({ asked_at: "2026-11-10T10:00:00Z" });
    expect(formatApprovalPrompt([stale], NOW)).toContain("Asked 2d ago.");
  });

  it("lists several actions as one numbered message, in the order given", () => {
    const prompt = formatApprovalPrompt(
      [
        card({
          approval_id: "ap_2",
          asked_at: "2026-11-12T09:59:00Z",
          summary: "Delete a calendar event from Work",
          description: {
            action: "Delete a calendar event",
            headline: "Delete a calendar event from Work",
            confirm: "delete it",
            details: [],
          },
        }),
        card({ asked_at: "2026-11-12T09:58:00Z" }),
      ],
      NOW,
    );
    expect(prompt).toBe(
      [
        "2 things need your OK:",
        "",
        "1. Delete a calendar event from Work",
        '2. Send an email to bob@x.com, jane@y.com: "Q3 numbers"',
        "",
        'Reply yes to all, no to all, or pick some: "yes 1 and 3".',
      ].join("\n"),
    );
  });

  it("falls back to the one-line summary on a card saved before descriptions", () => {
    const legacy = card({
      description: undefined,
      summary: "Gmail send email",
    });
    expect(formatApprovalPrompt([legacy], NOW)).toBe(
      "GAIA wants to gmail send email\n\nReply yes to go ahead, or no to cancel.",
    );
  });

  it("sends nothing when no approval is still pending", () => {
    expect(formatApprovalPrompt([card({ status: "approved" })], NOW)).toBe("");
  });

  it.each(Object.entries(PLATFORM_MARKDOWN))(
    "renders on %s with every fact intact",
    (_platform, render) => {
      const rendered = render(formatApprovalPrompt([card()], NOW));
      expect(rendered).toContain("send an email");
      // Slack links addresses (<mailto:…|…>); every recipient must still be there.
      expect(rendered).toContain("bob@x.com");
      expect(rendered).toContain("jane@y.com");
      expect(rendered).toContain("Reply yes to send it, or no to cancel.");
    },
  );
});
