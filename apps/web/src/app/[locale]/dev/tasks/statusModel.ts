import type { Task, TaskAsk } from "./taskModel";
import { watchStatus } from "./watchModel";
import { checkDay } from "./whenModel";

/** A sentence ends in one full stop, whatever GAIA's line ended with. */
const sentence = (text: string) => `${text.replace(/[.\s]+$/, "")}.`;

/**
 * Where a one-off GAIA task stands, in plain words: GAIA's latest line, then
 * what it waits on and when it looks again (waiting_on and scheduled_at).
 */
export function statusLine(task: Task): string | undefined {
  // A watch stands where its latest reading is; one that can't see says so in its ask.
  if (task.when.watch)
    return task.when.watch.blind ? undefined : watchStatus(task);
  const next = task.nextCheck ? checkDay(task.nextCheck) : undefined;
  if (task.state !== "waiting" || !next) return task.status;
  switch (task.waitingOn) {
    case "sub_todos":
      return `Waiting on its subtasks. Checks again ${next}.`;
    case "unplanned":
      return `Not planned yet. GAIA plans it ${next}.`;
    case "user":
      // The question itself says this, in the ask.
      return undefined;
    default:
      return task.status
        ? `${sentence(task.status)} Checks again ${next}.`
        : `Checks again ${next}.`;
  }
}

/** What happens to an unanswered question (if_no_reply), by when it expires. */
export function noReplyLine(
  plan: NonNullable<TaskAsk["ifNoReply"]>,
  expires?: string,
): string {
  if (plan.plan === "hold") return "GAIA waits until you answer.";
  const by = expires ? `No reply by ${checkDay(expires)}` : "No reply";
  if (plan.plan === "ask_again") return `${by} and GAIA asks once more.`;
  return `${by} and GAIA ${plan.defaultAction ?? "goes ahead"}.`;
}
