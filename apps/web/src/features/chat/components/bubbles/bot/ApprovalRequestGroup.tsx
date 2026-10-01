"use client";

import { Button } from "@heroui/button";
import { ShieldIcon } from "@icons";
import type {
  ApprovalDecision,
  ApprovalRequestData,
  ApprovalStatus,
} from "@shared/chat";
import { useEffect, useState } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { useMarkApprovalDecided } from "@/features/chat/hooks/useMarkApprovalDecided";
import {
  BATCH_OUTCOME_REASON,
  resolveBatchOutcomeStatus,
} from "@/features/chat/utils/batchOutcome";
import { toast } from "@/lib/toast";
import ApprovalRequestSection from "./ApprovalRequestSection";
import { useApprovalResolver } from "./ApprovalResolveContext";
import ApprovalReviewSheet from "./ApprovalReviewSheet";

/** A withdrawn approval stays visible just long enough to prove the agent
 * self-corrected — then collapses. Silent deletion reads as "did it send?". */
const TOMBSTONE_MS = 10000;

function RevokedTombstone({ item }: { item: ApprovalRequestData }) {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const timer = setTimeout(() => setVisible(false), TOMBSTONE_MS);
    return () => clearTimeout(timer);
  }, []);
  if (!visible) return null;
  return (
    <div className="w-full rounded-2xl bg-zinc-800/60 p-3 text-xs text-zinc-500">
      Agent withdrew: {item.summary} — no action needed.
    </div>
  );
}

interface ApprovalRequestGroupProps {
  items: ApprovalRequestData[];
  /** The conversation owning these cards — clears that stream's gate instead
   * of the active one. */
  conversationId?: string;
}

/**
 * Pending approvals render as cards; a decided one collapses into an
 * outcome chip on its tool's row instead (see ApprovalOutcomeChip). With
 * several pending, a review bar decides the whole set while per-card
 * buttons still allow partial answers.
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
  const revoked = items.filter((item) => item.status === "revoked");
  const [sheetOpen, setSheetOpen] = useState(false);

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
      markApprovalDecided(conversationId);
      const status: ApprovalStatus =
        decision === "approve" ? "approved" : "denied";
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
            isDisabled={batchSubmitting !== null}
            onPress={() => decideAll("approve")}
          >
            Approve all
          </Button>
          <Button
            variant="flat"
            size="sm"
            isDisabled={batchSubmitting !== null}
            onPress={() => decideAll("deny")}
          >
            Decline all
          </Button>
          {pending.length >= 3 && (
            <Button
              variant="bordered"
              size="sm"
              isDisabled={batchSubmitting !== null}
              onPress={() => setSheetOpen(true)}
            >
              {`Review ${pending.length}`}
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
      {revoked.map((item) => (
        <RevokedTombstone key={item.approval_id} item={item} />
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
