import type {
  DropReason,
  HoldReason,
  ItemState,
  UpdateRow,
} from "@shared/api/generated";
import { formatDistanceToNow } from "date-fns";

const DROP_REASON_LABELS: Partial<Record<DropReason, string>> = {
  nothing_new: "Nothing new",
  expired: "Expired",
  cancelled: "Cancelled",
  user_cancelled: "You said not to tell you",
};

const HOLD_REASON_LABELS: Record<HoldReason, string> = {
  quiet_hours: "Waiting for quiet hours to end",
  dnd: "Waiting for do not disturb to end",
  not_before: "Waiting for its time",
  checkin: "Waiting for your next check-in",
  gap: "Waiting a little after the last update",
  wait_for_run: "Waiting for a check due soon",
  in_call: "Waiting for your call to end",
  dormant: "Waiting for you to be back",
  bad_moment: "Waiting for a better moment",
  user_set: "Waiting for the time you asked for",
};

const ON_ITS_WAY: readonly ItemState[] = [
  "received",
  "queued",
  "composing",
  "sending",
];

export function updateStatusLabel(row: UpdateRow): string {
  if (row.resolved_at) return "Resolved";
  if (row.state === "sent") return "Told you";
  if (row.state === "held") {
    const waiting = row.hold_reason
      ? HOLD_REASON_LABELS[row.hold_reason]
      : "Waiting";
    return row.held_until
      ? `${waiting}, ${formatDistanceToNow(new Date(row.held_until), { addSuffix: true })}`
      : waiting;
  }
  if (row.state === "failed") return "Could not be delivered";
  if (ON_ITS_WAY.includes(row.state)) return "On its way";
  return (row.drop_reason && DROP_REASON_LABELS[row.drop_reason]) || "Recorded";
}

/** What the user is shown: the message they were told, else the line a system notice was written with, else what was recorded. */
export function updateBody(row: UpdateRow): string {
  const lines = row.told ?? (row.display ? [row.display.line] : row.facts);
  return lines.join("\n\n");
}

export function updateTime(row: UpdateRow): string {
  return formatDistanceToNow(new Date(row.told_at ?? row.occurred_at), {
    addSuffix: true,
  });
}
