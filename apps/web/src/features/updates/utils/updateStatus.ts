import type { DropReason, ItemState, UpdateRow } from "@shared/api/generated";
import { formatDistanceToNow } from "date-fns";

const DROP_REASON_LABELS: Partial<Record<DropReason, string>> = {
  nothing_new: "Nothing new",
  expired: "Expired",
  cancelled: "Cancelled",
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
    return row.held_until
      ? `Waiting, ${formatDistanceToNow(new Date(row.held_until), { addSuffix: true })}`
      : "Waiting";
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
