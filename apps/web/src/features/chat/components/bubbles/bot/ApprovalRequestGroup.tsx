"use client";

import { Button } from "@heroui/button";
import { ShieldIcon } from "@icons";
import {
  type ApprovalDecision,
  type ApprovalRequestData,
  type ApprovalStatus,
  isSettled,
} from "@shared/chat";
import { useState } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { toast } from "@/lib/toast";
import { ApprovalReceipts } from "./ApprovalReceipts";
import ApprovalRequestSection from "./ApprovalRequestSection";

interface ApprovalRequestGroupProps {
  items: ApprovalRequestData[];
}

interface LocalDecision {
  status: ApprovalStatus;
  feedback: string | null;
}

/**
 * Pending approvals render as actionable cards; a decided one moves into the collapsed
 * receipts list rather than disappearing. That list is also where auto mode's actions
 * show up — an action taken without asking still has to be visible after the fact.
 *
 * With several pending at once (a concurrent-subagent batch), a review bar offers one
 * decision for the whole set — the "review the cart" moment — while the per-card
 * buttons stay available for partial answers.
 *
 * A decision is settled locally because the resolved frame is published on the RESUMED
 * run's stream (a different message), so it never arrives to replace this card.
 */
export default function ApprovalRequestGroup({
  items,
}: ApprovalRequestGroupProps) {
  const [decided, setDecided] = useState<Record<string, LocalDecision>>({});
  const [batchSubmitting, setBatchSubmitting] =
    useState<ApprovalDecision | null>(null);

  const resolved = items.map((item) => {
    const local = decided[item.approval_id];
    return local ? { ...item, ...local } : item;
  });

  const pending = resolved.filter((item) => item.status === "pending");
  const settled = resolved.filter((item) => isSettled(item.status));

  const settleLocally = (approvalId: string, decision: LocalDecision) =>
    setDecided((prev) => ({ ...prev, [approvalId]: decision }));

  const decideAll = async (decision: ApprovalDecision) => {
    setBatchSubmitting(decision);
    try {
      const response = await chatApi.postApprovalBatchDecision({
        decisions: pending.map((item) => ({
          approval_id: item.approval_id,
          decision,
        })),
      });
      const status: ApprovalStatus =
        decision === "approve" ? "approved" : "denied";
      for (const outcome of response.outcomes) {
        // "not_found" means it was already resolved elsewhere — settle it here
        // too so the card doesn't linger; a genuinely failed item stays pending.
        if (outcome.resolved || outcome.reason === "not_found") {
          settleLocally(outcome.approval_id, { status, feedback: null });
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
              onDecided={(status, feedback) =>
                settleLocally(item.approval_id, { status, feedback })
              }
            />
          ))}
        </div>
      )}
      <ApprovalReceipts items={settled} />
    </div>
  );
}
