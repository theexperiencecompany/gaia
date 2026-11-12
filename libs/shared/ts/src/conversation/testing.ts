import type { FailureReason, ToolDataEntry } from "../api/generated";
import type {
  ConversationFrame,
  DisplayState,
  Entry,
  LiveTask,
  Reaction,
  UserMessage,
} from "./types";

/** Builders for conversation frames in tests, shaped as parseConversationEvent returns their frames. */

const AT = "2026-11-12T10:00:00+00:00";

export const userMessage = (
  id: string,
  text = `text of ${id}`,
  reaction: Reaction | null = null,
  revision = 0,
): UserMessage => ({
  kind: "user_message",
  id,
  text,
  surface: "web",
  platform_message_id: null,
  reply_to: null,
  retry_of: null,
  file_ids: [],
  files: [],
  selected_tool: null,
  tool_category: null,
  selected_workflow: null,
  selected_calendar_event: null,
  reply_to_message: null,
  voice: false,
  reaction,
  revision,
});

export const reply = (
  replyId: string,
  attemptId: string,
  text = "",
  revision = 0,
  quoteTarget: string | null = null,
): Entry => ({
  kind: "reply",
  id: `entry-${replyId}`,
  reply_id: replyId,
  attempt_id: attemptId,
  text,
  tool_data: [],
  follow_up_actions: [],
  heard_through: null,
  quote_target: quoteTarget,
  revision,
});

export const replySettled = (
  replyId: string,
  answers: string[],
  through: number,
  quoteTarget: string | null = null,
  outcome: "answered" | "stopped" | "failed" | "silent" = "answered",
  failure: FailureReason | null = null,
): Entry => ({
  kind: "reply_settled",
  id: `settled-${replyId}`,
  reply_id: replyId,
  outcome,
  answers,
  through,
  quote_target: quoteTarget,
  failure,
});

export const workStarted = (
  taskId: string,
  causeThrough: number,
  joins: string | null = null,
): Entry => ({
  kind: "work_started",
  id: `started-${taskId}`,
  task_id: taskId,
  cause_through: causeThrough,
  answers: [],
  joins,
});

export const workFinished = (
  taskId: string,
  outcome: "done" | "failed" | "cancelled" | "lost" = "done",
  toolData: ToolDataEntry[] = [],
): Entry => ({
  kind: "work_finished",
  id: `finished-${taskId}`,
  task_id: taskId,
  outcome,
  report: "report",
  tool_data: toolData,
});

export const approvalRequested = (
  taskId: string,
  approvalId: string,
): Entry => ({
  kind: "approval_requested",
  id: `requested-${approvalId}`,
  task_id: taskId,
  approval_id: approvalId,
  summary: "",
  expires_at: null,
});

export const approvalDecided = (approvalId: string): Entry => ({
  kind: "approval_decided",
  id: `decided-${approvalId}`,
  approval_id: approvalId,
  decision: "approve",
});

export const stopRequested = (
  id: string,
  coversThrough: number | null = null,
): Entry => ({
  kind: "stop_requested",
  id,
  by: "user",
  covers_through: coversThrough,
});

export const notice = (id: string, text = `notice ${id}`): Entry => ({
  kind: "notice",
  id,
  text,
  origin: "reminder",
});

export const entryFrame = (seq: number, entry: Entry): ConversationFrame => ({
  kind: "entry",
  seq,
  at: AT,
  entry,
});

export const entryUpdatedFrame = (
  seq: number,
  entry: Entry,
): ConversationFrame => ({
  kind: "entry_updated",
  seq,
  entry,
});

export const replyDelta = (
  attemptId: string,
  replyId: string | null,
  index: number,
  chunk: string,
): ConversationFrame => ({
  kind: "reply_delta",
  attempt_id: attemptId,
  reply_id: replyId,
  index,
  payload: { type: "response", chunk },
});

export const workCardDelta = (
  taskId: string,
  index: number,
  message: string,
): ConversationFrame => ({
  kind: "work_delta",
  task_id: taskId,
  index,
  payload: {
    type: "tool_data",
    entry: {
      tool_name: "tool_calls_data",
      tool_category: "gmail",
      data: { tool_name: "send", tool_call_id: `${taskId}-${index}`, message },
      timestamp: AT,
    },
  },
});

export const retractFrame = (attemptId: string): ConversationFrame => ({
  kind: "retract",
  attempt_id: attemptId,
});

export const liveTask = (
  taskId: string,
  awaitingApproval = false,
): LiveTask => ({
  task_id: taskId,
  awaiting_approval: awaitingApproval,
});

export const stateFrame = (
  head: number,
  display: DisplayState,
  work: LiveTask[] = [],
): ConversationFrame => ({ kind: "state", head, display, work });

/** A deterministic PRNG, so a failing property run names the seed that reproduces it. */
export function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface GeneratedConversation {
  frames: ConversationFrame[];
  retractedAttempts: string[];
}

/** Marks every chunk an attempt streams, so a test can find that attempt's text on screen. */
export const attemptMarker = (attemptId: string) => `<${attemptId}>`;

// Plays the server's side of a conversation, one episode at a time, keeping every frame valid.
class ConversationScript {
  readonly frames: ConversationFrame[] = [];
  readonly retractedAttempts: string[] = [];
  private seq = 0;
  private counter = 0;
  private readonly liveTasks: LiveTask[] = [];
  private readonly unanswered: string[] = [];
  private readonly indices = new Map<string, number>();
  private lastMessageId: string | null = null;

  constructor(private readonly random: () => number) {}

  get hasEntries(): boolean {
    return this.seq > 0;
  }

  get hasLiveWork(): boolean {
    return this.liveTasks.length > 0;
  }

  /** A user message answered by one reply, after any number of restarted attempts. */
  userTurn(mayStayOpen: boolean): void {
    const messageId = this.next("m");
    this.unanswered.push(messageId);
    this.lastMessageId = messageId;
    this.append(userMessage(messageId));
    this.publish("thinking");
    const replyId = this.next("r");
    let attemptId = this.next("a");
    while (this.chance(0.3)) {
      this.streamReply(attemptId, null, this.chunks(1));
      this.frames.push(retractFrame(attemptId));
      this.retractedAttempts.push(attemptId);
      attemptId = this.next("a");
    }
    this.streamReply(attemptId, null, this.chunks(1));
    const replySeq = this.append(reply(replyId, attemptId));
    this.streamReply(attemptId, replyId, this.chunks(0));
    if (mayStayOpen && this.chance(0.5)) return;
    const saved = reply(replyId, attemptId, `saved ${replyId}`, 1);
    this.frames.push(entryUpdatedFrame(replySeq, saved));
    if (this.chance(0.3)) {
      const reacted = userMessage(
        messageId,
        undefined,
        { emoji: "👍", by: "jev" },
        1,
      );
      this.frames.push(entryUpdatedFrame(this.seqOf(messageId), reacted));
    }
    const quote = this.chance(0.3) ? messageId : null;
    this.append(
      replySettled(replyId, this.unanswered.splice(0), this.seq, quote),
    );
    this.publishSettled();
  }

  startWork(): void {
    const taskId = this.next("k");
    this.liveTasks.push(liveTask(taskId));
    this.append(workStarted(taskId, this.seq));
    this.publish("working");
    this.streamWork(taskId, this.chunks(1));
    if (!this.chance(0.4)) return;
    const approvalId = this.next("p");
    this.append(approvalRequested(taskId, approvalId));
    this.setApproval(taskId, true);
    this.publish("awaiting_approval");
    this.append(approvalDecided(approvalId));
    this.setApproval(taskId, false);
    this.publish("working");
  }

  /** The task's work ends and its narrating reply (reply_id = task_id) settles it. */
  finishWork(): void {
    const [task] = this.liveTasks.splice(0, 1);
    this.append(workFinished(task.task_id));
    this.publish(this.hasLiveWork ? "working" : "thinking");
    const attemptId = this.next("a");
    this.streamReply(attemptId, null, this.chunks(1));
    this.append(reply(task.task_id, attemptId));
    const cause = this.lastMessageId;
    const answers = cause === null ? [] : [cause];
    const outcome = cause === null ? "failed" : "answered";
    this.append(
      replySettled(task.task_id, answers, this.seq - 1, null, outcome),
    );
    this.publishSettled();
  }

  notice(): void {
    this.append(notice(this.next("n")));
    this.publishSettled();
  }

  stop(): void {
    this.append(stopRequested(this.next("s")));
    for (const task of this.liveTasks.splice(0)) {
      this.append(workFinished(task.task_id, "cancelled"));
    }
    this.publish("idle");
  }

  private seqOf(entryId: string): number {
    const found = this.frames.find(
      (frame) => frame.kind === "entry" && frame.entry.id === entryId,
    );
    if (found?.kind !== "entry") throw new Error(`no entry ${entryId}`);
    return found.seq;
  }

  private setApproval(taskId: string, awaiting: boolean): void {
    const at = this.liveTasks.findIndex((task) => task.task_id === taskId);
    this.liveTasks[at] = liveTask(taskId, awaiting);
  }

  private chance(p: number): boolean {
    return this.random() < p;
  }

  private chunks(min: number): number {
    return min + Math.floor(this.random() * 3);
  }

  private next(prefix: string): string {
    this.counter += 1;
    return `${prefix}${this.counter}`;
  }

  private nextIndex(stream: string): number {
    const index = this.indices.get(stream) ?? 0;
    this.indices.set(stream, index + 1);
    return index;
  }

  private append(entry: Entry): number {
    this.seq += 1;
    this.frames.push(entryFrame(this.seq, entry));
    return this.seq;
  }

  private publish(display: DisplayState): void {
    this.frames.push(stateFrame(this.seq, display, [...this.liveTasks]));
  }

  private publishSettled(): void {
    this.publish(this.hasLiveWork ? "working" : "idle");
  }

  private streamReply(
    attemptId: string,
    replyId: string | null,
    chunks: number,
  ): void {
    for (let i = 0; i < chunks; i++) {
      const index = this.nextIndex(attemptId);
      this.frames.push(
        replyDelta(
          attemptId,
          replyId,
          index,
          `${attemptMarker(attemptId)}${index} `,
        ),
      );
    }
  }

  private streamWork(taskId: string, chunks: number): void {
    for (let i = 0; i < chunks; i++) {
      this.frames.push(
        workCardDelta(taskId, this.nextIndex(taskId), `step ${i}`),
      );
    }
  }
}

/** A random but server-valid frame sequence: bursts, restarts, replies, work, approvals and stops. */
export function generateConversation(
  seed: number,
  episodes = 12,
): GeneratedConversation {
  const random = seededRandom(seed);
  const script = new ConversationScript(random);
  for (let episode = 0; episode < episodes; episode++) {
    const roll = random();
    // Only the last reply may stay open: the server refuses a second open reply.
    if (roll < 0.45) script.userTurn(episode === episodes - 1);
    else if (!script.hasEntries) continue;
    else if (roll < 0.65) script.startWork();
    else if (roll < 0.8 && script.hasLiveWork) script.finishWork();
    else if (roll < 0.9) script.notice();
    else script.stop();
  }
  return { frames: script.frames, retractedAttempts: script.retractedAttempts };
}
