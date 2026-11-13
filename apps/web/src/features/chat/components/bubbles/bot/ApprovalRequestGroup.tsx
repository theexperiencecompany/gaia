"use client";

import { Button } from "@heroui/button";
import { ShieldIcon } from "@icons";
import type {
  ApprovalDecision,
  ApprovalRequestData,
  SettledApprovalCardData,
} from "@shared/chat";
import { settleCard } from "@shared/chat";
import { useState } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { APPROVAL_COPY } from "@/features/chat/constants/approvalCopy";
import { useMarkApprovalDecided } from "@/features/chat/hooks/useMarkApprovalDecided";
import {
  BATCH_OUTCOME_REASON,
  resolveBatchOutcomeStatus,
} from "@/features/chat/utils/batchOutcome";
import { toast } from "@/lib/toast";
import ApprovalRequestSection from "./ApprovalRequestSection";
import { useApprovalResolver } from "./ApprovalResolveContext";
import ApprovalReviewSheet from "./ApprovalReviewSheet";
import ApprovalSettledLine from "./ApprovalSettledLine";

interface ApprovalRequestGroupProps {
  items: ApprovalRequestData[];
  /** The conversation owning these cards — clears that stream's gate instead
   * of the active one. */
  conversationId?: string;
}

/**
 * Pending approvals render as cards; a decided one stays as a compact line
 * saying what happened. With several pending, a review bar decides the whole
 * set while per-card buttons still allow partial answers.
 *
 * A decision writes back to this message's tool_data via TextBubble's
 * resolver — the resolved frame publishes on a different (RESUMED) stream, so persisting here clears the pill and survives reload.
 */
export default function ApprovalRequestGroup({
  items,
  conversationId,
}: ApprovalRequestGroupProps) {
  const resolveApproval = useApprovalResolver();
  const [batchSubmitting, setBatchSubmitting] =
    useState<ApprovalDecision | null>(null);
  const markApprovalDecided = useMarkApprovalDecided();

  const pending = items.filter((item) => item.status === "pending");
  const settled = items.filter((item) => item.status !== "pending");
  const [sheetOpen, setSheetOpen] = useState(false);

  const settle = (
    approvalId: string,
    status: SettledApprovalCardData["status"],
    feedback: string | null,
  ) => {
    const item = items.find((i) => i.approval_id === approvalId);
    if (item) resolveApproval?.(approvalId, settleCard(item, status, feedback));
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
      markApprovalDecided(
        conversationId,
        decision === "approve"
          ? APPROVAL_COPY.carryingOnWithDecisions
          : APPROVAL_COPY.tellingGaiaNo,
      );
      const status = decision === "approve" ? "approved" : "denied";
      for (const outcome of response.outcomes) {
        // Settle to the server's state, not the tapped button: not_found means
        // the row was decided elsewhere. Falls back to the tap when the server
        // sent no state.
        if (outcome.resolved) {
          settle(outcome.approval_id, status, null);
        } else if (outcome.reason === BATCH_OUTCOME_REASON.NOT_FOUND) {
          settle(
            outcome.approval_id,
            resolveBatchOutcomeStatus(outcome.status, status),
            null,
          );
        }
      }
      if (
        response.outcomes.some(
          (o) => !o.resolved && o.reason !== BATCH_OUTCOME_REASON.NOT_FOUND,
        )
      ) {
        toast.error(APPROVAL_COPY.batchPartlyFailed);
      }
    } catch {
      toast.error(APPROVAL_COPY.batchFailed);
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
            {APPROVAL_COPY.groupTitle(pending.length)}
          </div>
          <Button
            color="primary"
            size="sm"
            isDisabled={batchSubmitting !== null}
            onPress={() => decideAll("approve")}
          >
            {APPROVAL_COPY.approveAll}
          </Button>
          <Button
            variant="flat"
            size="sm"
            isDisabled={batchSubmitting !== null}
            onPress={() => decideAll("deny")}
          >
            {APPROVAL_COPY.declineAll}
          </Button>
          {pending.length >= 3 && (
            <Button
              variant="bordered"
              size="sm"
              isDisabled={batchSubmitting !== null}
              onPress={() => setSheetOpen(true)}
            >
              {APPROVAL_COPY.review(pending.length)}
            </Button>
          )}
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
              conversationId={conversationId}
              onDecided={(status, feedback) =>
                settle(item.approval_id, status, feedback)
              }
            />
          ))}
        </div>
      )}
      {settled.map((item) => (
        <ApprovalSettledLine key={item.approval_id} data={item} />
      ))}
      <ApprovalReviewSheet
        items={pending}
        open={sheetOpen}
        conversationId={conversationId}
        onClose={() => setSheetOpen(false)}
        onSettled={settle}
      />
    </div>
  );
}
