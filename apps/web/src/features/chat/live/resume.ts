import { type ConversationView, ENTRY_KIND } from "@shared/conversation";

/**
 * The seq to resume the events stream after: just before the oldest entry that can
 * still change in place (an unsettled reply, or a user message no settled reply has
 * reached yet, whose reaction may still arrive), else the newest held seq.
 */
export function resumeAfter(view: ConversationView): number {
  const settledReplies = new Set<string>();
  let settledThrough = 0;
  for (const { entry } of view.entries) {
    if (entry.kind !== ENTRY_KIND.REPLY_SETTLED) continue;
    settledReplies.add(entry.reply_id);
    settledThrough = Math.max(settledThrough, entry.through);
  }
  const open = view.entries.find(
    ({ seq, entry }) =>
      (entry.kind === ENTRY_KIND.REPLY &&
        !settledReplies.has(entry.reply_id)) ||
      (entry.kind === ENTRY_KIND.USER_MESSAGE && seq > settledThrough),
  );
  if (open) return open.seq - 1;
  return view.entries.at(-1)?.seq ?? 0;
}
