"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { ShieldIcon } from "@icons";
import type {
  ApprovalDecision,
  ApprovalRequestData,
  ApprovalStatus,
  BatchDecisionOutcome,
} from "@shared/chat";
import { formatApprovalAge } from "@shared/chat";
import { flattenArgsPreview } from "@shared/utils";
import { useState } from "react";
import { chatApi } from "@/features/chat/api/chatApi";
import { useMarkApprovalDecided } from "@/features/chat/hooks/useMarkApprovalDecided";
import {
  BATCH_OUTCOME_REASON,
  resolveBatchOutcomeStatus,
} from "@/features/chat/utils/batchOutcome";
import { toast } from "@/lib/toast";

interface SheetDecision {
  decision: ApprovalDecision;
  feedback: string;
}

interface ApprovalReviewSheetProps {
  items: ApprovalRequestData[];
  open: boolean;
  onClose: () => void;
  /** The conversation owning these cards — clears that stream's gate instead
   * of the active one. */
  conversationId?: string;
  onSettled: (
    approvalId: string,
    status: ApprovalStatus,
    feedback: string | null,
  ) => void;
}

/**
 * Settle one batch outcome: server truth wins over the tapped button, so a
 * lost race never paints the wrong verdict. Any other uncommitted item keeps
 * its decision in the sheet for review or retry.
 */
function settleBatchOutcome(
  outcome: BatchDecisionOutcome,
  made: SheetDecision,
  onSettled: ApprovalReviewSheetProps["onSettled"],
  removeDecision: (approvalId: string) => void,
): void {
  if (outcome.resolved) {
    onSettled(
      outcome.approval_id,
      made.decision === "approve" ? "approved" : "denied",
      made.feedback.trim() || null,
    );
    removeDecision(outcome.approval_id);
    return;
  }
  if (outcome.reason === BATCH_OUTCOME_REASON.NOT_FOUND) {
    onSettled(
      outcome.approval_id,
      resolveBatchOutcomeStatus(
        outcome.status,
        made.decision === "approve" ? "approved" : "denied",
      ),
      made.feedback.trim() || null,
    );
    removeDecision(outcome.approval_id);
  }
}

/**
 * Bottom sheet for 3+ pending approvals. Same rows as the inline cards, one
 * Submit flushing only what's decided — the rest stay pending, and rows that
 * arrive mid-review never reset existing decisions (keyed by approval_id).
 */
export default function ApprovalReviewSheet({
  items,
  open,
  onClose,
  conversationId,
  onSettled,
}: ApprovalReviewSheetProps) {
  const [decisions, setDecisions] = useState<Record<string, SheetDecision>>({});
  const [submitting, setSubmitting] = useState(false);
  const markApprovalDecided = useMarkApprovalDecided();

  const toggle = (approvalId: string, decision: ApprovalDecision) => {
    setDecisions((prev) => {
      const next = { ...prev };
      if (next[approvalId]?.decision === decision) {
        delete next[approvalId];
      } else {
        next[approvalId] = {
          decision,
          feedback: next[approvalId]?.feedback ?? "",
        };
      }
      return next;
    });
  };

  const setFeedback = (approvalId: string, feedback: string) => {
    setDecisions((prev) =>
      prev[approvalId]
        ? { ...prev, [approvalId]: { ...prev[approvalId], feedback } }
        : prev,
    );
  };

  const decidedIds = Object.keys(decisions);

  const submit = async () => {
    if (decidedIds.length === 0 || submitting) return;
    setSubmitting(true);
    try {
      const response = await chatApi.postApprovalBatchDecision({
        decisions: decidedIds.map((approval_id) => ({
          approval_id,
          decision: decisions[approval_id].decision,
          feedback: decisions[approval_id].feedback.trim() || undefined,
        })),
      });
      markApprovalDecided(conversationId);
      const removeDecision = (approvalId: string) => {
        setDecisions((prev) => {
          const next = { ...prev };
          delete next[approvalId];
          return next;
        });
      };
      for (const outcome of response.outcomes) {
        const made = decisions[outcome.approval_id];
        if (made) settleBatchOutcome(outcome, made, onSettled, removeDecision);
      }
      const kept = response.outcomes.filter(
        (o) => !o.resolved && o.reason !== BATCH_OUTCOME_REASON.NOT_FOUND,
      );
      if (kept.some((o) => o.reason === BATCH_OUTCOME_REASON.STALE)) {
        toast.error("Some approvals already moved — kept for review");
      }
      if (kept.some((o) => o.reason !== BATCH_OUTCOME_REASON.STALE)) {
        toast.error("Some approvals couldn't be submitted — please try again");
      }
    } catch {
      toast.error("Couldn't submit your decisions — please try again");
    } finally {
      setSubmitting(false);
    }
  };

  const groups = new Map<string, ApprovalRequestData[]>();
  for (const item of items) {
    const key = item.integration_name ?? "Other";
    const list = groups.get(key) ?? [];
    list.push(item);
    groups.set(key, list);
  }
  const totals = [...groups.entries()]
    .map(([name, list]) => `${list.length} ${name}`)
    .join(", ");

  return (
    <Modal isOpen={open} onClose={onClose} placement="bottom-center" size="lg">
      <ModalContent>
        <ModalHeader className="flex items-center gap-2">
          <ShieldIcon width={18} className="shrink-0 text-amber-400" />
          <span className="text-sm text-zinc-100">
            {items.length} actions need your approval ({totals})
          </span>
        </ModalHeader>
        <ModalBody className="max-h-[50vh] overflow-y-auto">
          {[...groups.entries()].map(([name, list]) => (
            <div key={name}>
              <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                {name}
              </div>
              <div className="mb-3 space-y-2">
                {list.map((item) => {
                  const picked = decisions[item.approval_id]?.decision ?? null;
                  const preview = flattenArgsPreview(item.args_preview ?? {});
                  const shown = preview.rows.slice(0, 6);
                  const hidden =
                    preview.rows.length - shown.length + preview.omitted;
                  return (
                    <div
                      key={item.approval_id}
                      data-testid="sheet-row"
                      className="rounded-2xl bg-zinc-900 p-3"
                    >
                      <div className="text-sm leading-snug text-zinc-100">
                        {item.summary}
                      </div>
                      {item.age_seconds != null && (
                        <div className="mt-0.5 text-[11px] text-zinc-500">
                          {formatApprovalAge(item.age_seconds)}
                        </div>
                      )}
                      {shown.length > 0 && (
                        <div className="mt-1.5 space-y-0.5">
                          {shown.map((row) => (
                            <div
                              key={`${row.group ?? "top"}:${row.key}`}
                              className="text-xs text-zinc-400"
                            >
                              <span className="text-zinc-500">
                                {row.group != null ? `${row.group} ` : ""}
                                {row.key.replaceAll("_", " ")}:{" "}
                              </span>
                              {row.value}
                            </div>
                          ))}
                          {hidden > 0 && (
                            <div className="text-[11px] text-zinc-500">
                              +{hidden} more
                            </div>
                          )}
                        </div>
                      )}
                      <div className="mt-2 flex items-center gap-2">
                        <Button
                          size="sm"
                          color={picked === "approve" ? "primary" : "default"}
                          variant={picked === "approve" ? "solid" : "flat"}
                          onPress={() => toggle(item.approval_id, "approve")}
                        >
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant={picked === "deny" ? "solid" : "flat"}
                          color={picked === "deny" ? "danger" : "default"}
                          onPress={() => toggle(item.approval_id, "deny")}
                        >
                          Deny
                        </Button>
                        {picked === "deny" && (
                          <Input
                            className="flex-1"
                            size="sm"
                            variant="flat"
                            placeholder="Why? (optional)"
                            value={decisions[item.approval_id]?.feedback ?? ""}
                            onValueChange={(value) =>
                              setFeedback(item.approval_id, value)
                            }
                          />
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </ModalBody>
        <ModalFooter className="flex items-center justify-between">
          <span className="text-xs text-zinc-500">
            Each decision acts immediately; Submit closes up and tells your
            agent.
          </span>
          <Button
            color="primary"
            isDisabled={decidedIds.length === 0 || submitting}
            onPress={submit}
          >
            {`Submit (${decidedIds.length})`}
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}
