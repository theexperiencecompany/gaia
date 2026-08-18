"use client";

import { Button } from "@heroui/button";
import { ShieldIcon } from "@icons";
import type {
  ApprovalDecision,
  ApprovalRequestData,
  ApprovalStatus,
} from "@shared/chat";
import { useState } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { useMarkApprovalDecided } from "@/features/chat/hooks/useMarkApprovalDecided";
import { toast } from "@/lib/toast";
import ApprovalRequestSection from "./ApprovalRequestSection";
import { useApprovalResolver } from "./ApprovalResolveContext";

interface ApprovalRequestGroupProps {
  items: ApprovalRequestData[];
}

/**
 * Pending approvals render as actionable cards; a decided one collapses into an
 * outcome chip on its tool's own row in the "Used N tools" thread (see
 * ApprovalOutcomeChip), so nothing renders here once it settles.
 *
 * With several pending at once (a concurrent-subagent batch), a review bar offers one
 * decision for the whole set — the "review the cart" moment — while the per-card
 * buttons stay available for partial answers.
 *
 * A decision is written back into this message's tool_data (via the resolver from
 * TextBubble): the resolved frame is published on the RESUMED run's stream, a different
 * message, so it never arrives to replace this card. Persisting it here clears the
 * derived "Waiting for approval" pill and survives reload.
 */
export default function ApprovalRequestGroup({
  items,
}: ApprovalRequestGroupProps) {
  const resolveApproval = useApprovalResolver();
  const [batchSubmitting, setBatchSubmitting] =
    useState<ApprovalDecision | null>(null);
  const markApprovalDecided = useMarkApprovalDecided();

  const pending = items.filter((item) => item.status === "pending");

  const settle = (
    approvalId: string,
    status: ApprovalStatus,
    feedback: string | null,
  ) => {
    const item = items.find((i) => i.approval_id === approvalId);
    if (item) resolveApproval?.(approvalId, { ...item, status, feedback });
  };

  const decideAll = async (decision: ApprovalDecision) => {
    setBatchSubmitting(decision);
    try {
      const response = await chatApi.postApprovalBatchDecision({
        decisions: pending.map((item) => ({
          approval_id: item.approval_id,
          decision,
        })),
      });
      markApprovalDecided();
      const status: ApprovalStatus =
        decision === "approve" ? "approved" : "denied";
      for (const outcome of response.outcomes) {
        // "not_found" means it was already resolved elsewhere — settle it here
        // too so the card doesn't linger; a genuinely failed item stays pending.
        if (outcome.resolved || outcome.reason === "not_found") {
          settle(outcome.approval_id, status, null);
        }
      }
      if (
        response.outcomes.some((o) => !o.resolved && o.reason !== "not_found")
      ) {
        toast.error("Some approvals couldn't be submitted — please try again");
      }
    } catch {
      toast.error("Couldn't submit your decisions — please try again");
    } finally {
      setBatchSubmitting(null);
    }
  };

  return (
    <div className="flex w-full max-w-2xl flex-col gap-3">
      {pending.length > 1 && (
        <div className="flex w-full items-center gap-3 rounded-2xl bg-zinc-800 p-4">
          <ShieldIcon width={18} className="shrink-0 text-amber-400" />
          <div className="min-w-0 flex-1 text-sm text-zinc-100">
            {pending.length} actions need your approval
          </div>
          <Button
            color="primary"
            size="sm"
            isLoading={batchSubmitting === "approve"}
            isDisabled={batchSubmitting !== null}
            onPress={() => decideAll("approve")}
          >
            Approve all
          </Button>
          <Button
            variant="flat"
            size="sm"
            isLoading={batchSubmitting === "deny"}
            isDisabled={batchSubmitting !== null}
            onPress={() => decideAll("deny")}
          >
            Decline all
          </Button>
        </div>
      )}
      {pending.length > 0 && (
        <div
          className={
            pending.length === 1 ? "" : "grid grid-cols-1 gap-3 sm:grid-cols-2"
          }
        >
          {pending.map((item) => (
            <ApprovalRequestSection
              key={item.approval_id}
              data={item}
              disabled={batchSubmitting !== null}
              onDecided={(status, feedback) =>
                settle(item.approval_id, status, feedback)
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
