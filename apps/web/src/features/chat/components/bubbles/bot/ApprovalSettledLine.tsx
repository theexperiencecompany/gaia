import {
  Alert01Icon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  StopCircleIcon,
} from "@icons";
import type { ApprovalRequestData } from "@shared/chat";
import { approvalOutcomeLabel, cardDescription } from "@shared/chat";
import type { ReactNode } from "react";

const ICON_SIZE = { width: 16, height: 16 };

const DONE = (
  <CheckmarkCircle02Icon {...ICON_SIZE} className="shrink-0 text-emerald-400" />
);
const DECLINED = (
  <Cancel01Icon {...ICON_SIZE} className="shrink-0 text-zinc-400" />
);
const STOPPED = (
  <StopCircleIcon {...ICON_SIZE} className="shrink-0 text-zinc-400" />
);
const PROBLEM = (
  <Alert01Icon {...ICON_SIZE} className="shrink-0 text-amber-400" />
);

const OUTCOME_ICON: Record<
  Exclude<ApprovalRequestData["status"], "pending">,
  ReactNode
> = {
  approved: DONE,
  auto_approved: DONE,
  executed: DONE,
  denied: DECLINED,
  revoked: STOPPED,
  cancelled: STOPPED,
  abandoned: STOPPED,
  timeout: STOPPED,
  failed: PROBLEM,
  unknown: PROBLEM,
};

/**
 * What became of a decided approval, in place of its card: the outcome in plain
 * words, the action it was about, and the reason or error when there is one.
 */
export default function ApprovalSettledLine({
  data,
}: Readonly<{ data: ApprovalRequestData }>) {
  if (data.status === "pending") return null;
  const reason = data.feedback?.trim();
  return (
    <div
      data-testid="approval-settled"
      className="flex w-full max-w-md items-start gap-2.5 rounded-2xl bg-zinc-800 p-4"
    >
      {OUTCOME_ICON[data.status]}
      <div className="min-w-0 flex-1 text-sm leading-snug">
        <div className="text-zinc-100">{approvalOutcomeLabel(data)}</div>
        <div className="mt-0.5 truncate text-xs text-zinc-400">
          {cardDescription(data).headline}
        </div>
        {reason && data.status !== "auto_approved" && (
          <div className="mt-0.5 text-xs text-zinc-500">{reason}</div>
        )}
      </div>
    </div>
  );
}
