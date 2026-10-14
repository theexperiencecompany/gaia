// @vitest-environment jsdom

import { ApiError } from "@shared/api";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "@/features/chat/api/chatApi";

const post = vi.fn();

vi.mock("@/lib/api/typed", () => ({
  api: { post: (...args: unknown[]) => post(...args) },
}));

const HTTP_GONE = 410;

describe("chatApi approval decisions", () => {
  beforeEach(() => {
    post.mockReset();
  });

  it("maps 410 to not_found instead of painting the tapped verdict", async () => {
    post.mockRejectedValue(new ApiError("Gone", HTTP_GONE));
    const outcome = await chatApi.postApprovalDecision("ap_1", {
      decision: "approve",
    });
    expect(outcome).toEqual({ success: false, reason: "not_found" });
  });

  it("chunks batch decisions to the server 25-item cap", async () => {
    post.mockImplementation(
      async (_url: string, init: { body: { decisions: unknown[] } }) => ({
        outcomes: (init.body.decisions as { approval_id: string }[]).map(
          (d) => ({ approval_id: d.approval_id, resolved: true, reason: null }),
        ),
      }),
    );
    const decisions = Array.from({ length: 30 }, (_, i) => ({
      approval_id: `ap_${i}`,
      decision: "approve" as const,
    }));
    const response = await chatApi.postApprovalBatchDecision({ decisions });
    expect(post).toHaveBeenCalledTimes(2);
    expect(
      (post.mock.calls[0][1] as { body: { decisions: unknown[] } }).body
        .decisions,
    ).toHaveLength(25);
    expect(
      (post.mock.calls[1][1] as { body: { decisions: unknown[] } }).body
        .decisions,
    ).toHaveLength(5);
    expect(response.outcomes).toHaveLength(30);
  });

  it("keeps committed chunks' outcomes when another chunk fails", async () => {
    post.mockImplementation(
      async (_url: string, init: { body: { decisions: unknown[] } }) => {
        const ids = (init.body.decisions as { approval_id: string }[]).map(
          (d) => d.approval_id,
        );
        if (ids.includes("ap_25")) throw new ApiError("Bad gateway", 502);
        return {
          outcomes: ids.map((approval_id) => ({
            approval_id,
            resolved: true,
            reason: null,
          })),
        };
      },
    );
    const decisions = Array.from({ length: 30 }, (_, i) => ({
      approval_id: `ap_${i}`,
      decision: "approve" as const,
    }));
    const response = await chatApi.postApprovalBatchDecision({ decisions });
    expect(response.outcomes).toHaveLength(30);
    expect(response.outcomes.slice(0, 25).every((o) => o.resolved)).toBe(true);
    expect(response.outcomes.slice(25)).toEqual(
      decisions.slice(25).map(({ approval_id }) => ({
        approval_id,
        resolved: false,
        reason: "error",
      })),
    );
  });

  it("throws when no chunk committed, so the caller reports total failure", async () => {
    post.mockRejectedValue(new ApiError("Bad gateway", 502));
    const decisions = Array.from({ length: 30 }, (_, i) => ({
      approval_id: `ap_${i}`,
      decision: "approve" as const,
    }));
    await expect(
      chatApi.postApprovalBatchDecision({ decisions }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
