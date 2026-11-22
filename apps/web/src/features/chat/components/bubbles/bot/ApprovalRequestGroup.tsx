"use client";

import { ShieldIcon } from "@icons";
import type { ApprovalDecision, ApprovalRequestData } from "@shared/chat";
import { useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { chatApi } from "@/features/chat/api/chatApi";
import { isSettledOutcome } from "@/features/chat/utils/batchOutcome";
import { toast } from "@/lib/toast";
import ApprovalRequestSection from "./ApprovalRequestSection";
import ApprovalReviewSheet from "./ApprovalReviewSheet";

interface ApprovalRequestGroupProps {
  items: ApprovalRequestData[];
}

/**
 * Pending approvals render as cards; any other one, a withdrawn one included,
 * is the server's status as a chip on its tool's row (see ApprovalOutcomeChip). With
 * several pending, a review bar decides the whole set while per-card
 * buttons still allow partial answers.
 *
 * A decision writes back to this message's tool_data via TextBubble's
 * resolver — the resolved frame publishes on a different (RESUMED) stream, so persisting here clears the pill and survives reload.
 */
export default function ApprovalRequestGroup({
  items,
}: ApprovalRequestGroupProps) {
  const [batchSubmitting, setBatchSubmitting] =
    useState<ApprovalDecision | null>(null);

  const pending = items.filter((item) => item.status === "waiting");
  const [sheetOpen, setSheetOpen] = useState(false);

  const decideAll = async (decision: ApprovalDecision) => {
    setBatchSubmitting(decision);
    try {
      const response = await chatApi.postApprovalBatchDecision({
        decisions: pending.map((item) => ({
          approval_id: item.approval_id,
          decision,
        })),
      });
      // A decided card ends when the server's screen updates its item.
      if (response.outcomes.some((o) => !isSettledOutcome(o))) {
        toast.error("Some approvals couldn't be submitted, please try again");
      }
    } catch {
      toast.error("Couldn't submit your decisions, please try again");
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
          <GaiaButton
            size="sm"
            isDisabled={batchSubmitting !== null}
            onPress={() => decideAll("approve")}
            variant="primary"
          >
            Approve all
          </GaiaButton>
          <GaiaButton
            variant="default-soft"
            size="sm"
            isDisabled={batchSubmitting !== null}
            onPress={() => decideAll("deny")}
          >
            Decline all
          </GaiaButton>
          {pending.length >= 3 && (
            <GaiaButton
              variant="outline"
              size="sm"
              isDisabled={batchSubmitting !== null}
              onPress={() => setSheetOpen(true)}
            >
              {`Review ${pending.length}`}
            </GaiaButton>
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
            />
          ))}
        </div>
      )}
      <ApprovalReviewSheet
        items={pending}
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
      />
    </div>
  );
}
