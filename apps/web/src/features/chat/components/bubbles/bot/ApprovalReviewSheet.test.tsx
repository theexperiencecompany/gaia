// @vitest-environment jsdom

import type { ApprovalRequestData } from "@shared/chat";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "@/features/chat/api/chatApi";
import ApprovalRequestGroup from "@/features/chat/components/bubbles/bot/ApprovalRequestGroup";
import { toast } from "@/lib/toast";

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: {
    postApprovalDecision: vi.fn(),
    postApprovalBatchDecision: vi.fn(),
  },
}));

vi.mock("@/features/chat/hooks/useMarkApprovalDecided", () => ({
  useMarkApprovalDecided: () => () => undefined,
}));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn() },
}));

const card = (id: string, integration: string): ApprovalRequestData => ({
  approval_id: id,
  tool_call_id: `call-${id}`,
  gated_tool_name: "GMAIL_SEND_EMAIL",
  integration_name: integration,
  summary: `Send ${id}`,
  args_preview: { to: "b@x" },
  status: "pending",
  feedback: null,
  timeout_seconds: 300,
  age_seconds: 60,
  ledger_version: 0,
});

describe("ApprovalReviewSheet", () => {
  beforeEach(() => {
    vi.mocked(chatApi.postApprovalBatchDecision).mockReset().mockResolvedValue({
      outcomes: [],
    });
    vi.mocked(toast.error).mockReset();
  });

  it("offers a review sheet at three pendings, not below", () => {
    const { rerender } = render(
      <ApprovalRequestGroup items={[card("a", "gmail")]} />,
    );
    expect(screen.queryByRole("button", { name: /review/i })).toBeNull();
    rerender(
      <ApprovalRequestGroup
        items={[card("a", "gmail"), card("b", "cal"), card("c", "gmail")]}
      />,
    );
    expect(screen.getByRole("button", { name: /review 3/i })).toBeDefined();
  });

  it("submit flushes decided-only and leaves the rest pending", async () => {
    vi.mocked(chatApi.postApprovalBatchDecision).mockResolvedValue({
      outcomes: [
        { approval_id: "a", resolved: true, reason: null },
        { approval_id: "b", resolved: true, reason: null },
      ],
    });
    render(
      <ApprovalRequestGroup
        items={[card("a", "gmail"), card("b", "cal"), card("c", "gmail")]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /review 3/i }));
    const dialog = screen.getByRole("dialog");
    const rows = within(dialog).getAllByTestId("sheet-row");
    expect(rows).toHaveLength(3);
    const rowFor = (text: string) =>
      rows.find((row) => within(row).queryByText(text) !== null) ?? rows[0];
    fireEvent.click(
      within(rowFor("Send a")).getByRole("button", { name: /^approve$/i }),
    );
    fireEvent.click(
      within(rowFor("Send b")).getByRole("button", { name: /^deny$/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /submit \(2\)/i }));
    expect(chatApi.postApprovalBatchDecision).toHaveBeenCalledTimes(1);
    const payload = vi.mocked(chatApi.postApprovalBatchDecision).mock
      .calls[0][0];
    expect(payload.decisions).toHaveLength(2);
    expect(payload.decisions.map((d) => d.approval_id).sort()).toEqual([
      "a",
      "b",
    ]);
  });

  it("mid-review arrivals keep existing decisions", () => {
    const { rerender } = render(
      <ApprovalRequestGroup
        items={[card("a", "gmail"), card("b", "cal"), card("c", "gmail")]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /review 3/i }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(
      within(within(dialog).getAllByTestId("sheet-row")[0]).getByRole(
        "button",
        {
          name: /^approve$/i,
        },
      ),
    );
    rerender(
      <ApprovalRequestGroup
        items={[
          card("a", "gmail"),
          card("b", "cal"),
          card("c", "gmail"),
          card("d", "slack"),
        ]}
      />,
    );
    expect(screen.getByRole("button", { name: /submit \(1\)/i })).toBeDefined();
    expect(
      within(screen.getByRole("dialog")).getAllByTestId("sheet-row"),
    ).toHaveLength(4);
  });

  it("settles a lost race to the server state, not the tapped button", async () => {
    const { ApprovalResolveProvider } = await import(
      "@/features/chat/components/bubbles/bot/ApprovalResolveContext"
    );
    const settled: { id: string; status: string }[] = [];
    vi.mocked(chatApi.postApprovalBatchDecision).mockResolvedValue({
      outcomes: [
        {
          approval_id: "a",
          resolved: false,
          reason: "not_found",
          status: "denied",
        },
      ],
    });
    render(
      <ApprovalResolveProvider
        value={(approvalId, resolved) =>
          settled.push({ id: approvalId, status: resolved.status })
        }
      >
        <ApprovalRequestGroup
          items={[card("a", "gmail"), card("b", "cal"), card("c", "gmail")]}
        />
      </ApprovalResolveProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /review 3/i }));
    const dialog = screen.getByRole("dialog");
    const rows = within(dialog).getAllByTestId("sheet-row");
    const rowFor = (text: string) =>
      rows.find((row) => within(row).queryByText(text) !== null) ?? rows[0];
    fireEvent.click(
      within(rowFor("Send a")).getByRole("button", { name: /^approve$/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /submit \(1\)/i }));
    await vi.waitFor(() => expect(settled).toHaveLength(1));
    // Tapped approve, server says denied — the real verdict wins.
    expect(settled[0]).toEqual({ id: "a", status: "denied" });
  });

  it("settles the committed part of a partial batch and keeps the failed part for retry", async () => {
    const { ApprovalResolveProvider } = await import(
      "@/features/chat/components/bubbles/bot/ApprovalResolveContext"
    );
    const settled: string[] = [];
    vi.mocked(chatApi.postApprovalBatchDecision).mockResolvedValue({
      outcomes: [
        { approval_id: "a", resolved: true, reason: null },
        { approval_id: "b", resolved: false, reason: "error" },
      ],
    });
    render(
      <ApprovalResolveProvider value={(approvalId) => settled.push(approvalId)}>
        <ApprovalRequestGroup
          items={[card("a", "gmail"), card("b", "cal"), card("c", "gmail")]}
        />
      </ApprovalResolveProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /review 3/i }));
    const rows = within(screen.getByRole("dialog")).getAllByTestId("sheet-row");
    const rowFor = (text: string) =>
      rows.find((row) => within(row).queryByText(text) !== null) ?? rows[0];
    fireEvent.click(
      within(rowFor("Send a")).getByRole("button", { name: /^approve$/i }),
    );
    fireEvent.click(
      within(rowFor("Send b")).getByRole("button", { name: /^approve$/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /submit \(2\)/i }));
    await vi.waitFor(() => expect(settled).toEqual(["a"]));
    expect(screen.getByRole("button", { name: /submit \(1\)/i })).toBeDefined();
    expect(
      vi.mocked(toast.error).mock.calls.map(([message]) => message),
    ).toEqual(["Some approvals couldn't be submitted — please try again"]);
  });

  it("groups rows by integration with honest totals", () => {
    render(
      <ApprovalRequestGroup
        items={[card("a", "gmail"), card("b", "cal"), card("c", "gmail")]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /review 3/i }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/2.*gmail/i)).toBeDefined();
    expect(within(dialog).getByText(/1.*cal/i)).toBeDefined();
  });
});
