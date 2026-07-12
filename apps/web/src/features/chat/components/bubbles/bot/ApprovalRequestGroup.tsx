"use client";

import {
  type ApprovalRequestData,
  type ApprovalStatus,
  isSettled,
} from "@shared/chat";
import { useState } from "react";
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
 * A decision is settled locally because the resolved frame is published on the RESUMED
 * run's stream (a different message), so it never arrives to replace this card.
 */
export default function ApprovalRequestGroup({
  items,
}: ApprovalRequestGroupProps) {
  const [decided, setDecided] = useState<Record<string, LocalDecision>>({});

  const resolved = items.map((item) => {
    const local = decided[item.approval_id];
    return local ? { ...item, ...local } : item;
  });

  const pending = resolved.filter((item) => item.status === "pending");
  const settled = resolved.filter((item) => isSettled(item.status));

  return (
    <div className="flex w-full max-w-2xl flex-col gap-3">
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
                setDecided((prev) => ({
                  ...prev,
                  [item.approval_id]: { status, feedback },
                }))
              }
            />
          ))}
        </div>
      )}
      <ApprovalReceipts items={settled} />
    </div>
  );
}
