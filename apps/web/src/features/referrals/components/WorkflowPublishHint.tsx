"use client";

import { useReferralMe } from "../hooks/useReferrals";
import { REFERRAL_UI_COPY } from "../referralCopy";

interface WorkflowPublishHintProps {
  /** What publishing does, shown to everyone. */
  label: string;
}

/** The publish button's tooltip; a creator who can refer also learns that paying visitors fill their meter. */
export function WorkflowPublishHint({ label }: WorkflowPublishHintProps) {
  const referral = useReferralMe();
  if (referral.status !== "ready") return label;
  return (
    <div className="flex max-w-64 flex-col gap-1 py-1">
      <span>{label}</span>
      <span className="text-xs text-zinc-400">
        {REFERRAL_UI_COPY.workflowPublishLine(
          referral.me.workflow_meter.per_month,
        )}
      </span>
    </div>
  );
}
