import type { Entry, LoggedEntry, UserMessage } from "./entries";
import type {
  ConversationDisplay,
  ConversationFrame,
  WorkPhase,
} from "./frames";

/** Builders for conversation frames in tests, shaped as parseConversationFrame returns them. */

const AT = "2026-11-12T10:00:00+00:00";

export type DeltaTarget = { replyId: string } | { taskId: string };

export const logged = (seq: number, entry: Entry): LoggedEntry => ({
  seq,
  at: AT,
  entry,
});

export const userMessage = (
  id: string,
  text = `text of ${id}`,
): UserMessage => ({
  kind: "user_message",
  id,
  text,
  surface: "web",
  platform_message_id: null,
  reply_to: null,
  retry_of: null,
  file_ids: [],
  voice: false,
});

export const reply = (
  replyId: string,
  attemptId: string,
  text = "",
): Entry => ({
  kind: "reply",
  id: `entry-${replyId}`,
  reply_id: replyId,
  attempt_id: attemptId,
  text,
  tool_data: [],
  follow_up_actions: [],
  heard_through: null,
});

export const replySettled = (
  replyId: string,
  answers: string[],
  through: number,
  outcome: "answered" | "stopped" | "failed" | "silent" = "answered",
): Entry => ({
  kind: "reply_settled",
  id: `settled-${replyId}`,
  reply_id: replyId,
  outcome,
  answers,
  through,
});

export const workStarted = (taskId: string, causeThrough: number): Entry => ({
  kind: "work_started",
  id: `started-${taskId}`,
  task_id: taskId,
  cause_through: causeThrough,
  answers: [],
});

export const workFinished = (
  taskId: string,
  outcome: "done" | "failed" | "cancelled" | "lost" = "done",
): Entry => ({
  kind: "work_finished",
  id: `finished-${taskId}`,
  task_id: taskId,
  outcome,
  report: "report",
});

export const approvalRequested = (
  taskId: string,
  approvalId: string,
): Entry => ({
  kind: "approval_requested",
  id: `requested-${approvalId}`,
  task_id: taskId,
  approval_id: approvalId,
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
  entry: logged(seq, entry),
});

export const entryUpdatedFrame = (
  seq: number,
  entry: Entry,
): ConversationFrame => ({
  kind: "entry_updated",
  entry: logged(seq, entry),
});

const targetOf = (target: DeltaTarget) =>
  "replyId" in target
    ? { reply_id: target.replyId, task_id: null }
    : { reply_id: null, task_id: target.taskId };

export const textDelta = (
  attemptId: string,
  target: DeltaTarget,
  chunk: string,
): ConversationFrame => ({
  kind: "delta",
  attempt_id: attemptId,
  ...targetOf(target),
  payload: { type: "response", chunk },
});

export const toolCardDelta = (
  attemptId: string,
  target: DeltaTarget,
  toolCallId: string,
  message: string,
): ConversationFrame => ({
  kind: "delta",
  attempt_id: attemptId,
  ...targetOf(target),
  payload: {
    type: "tool_data",
    entry: {
      tool_name: "tool_calls_data",
      tool_category: "gmail",
      data: { tool_name: "send", tool_call_id: toolCallId, message },
      timestamp: AT,
    },
  },
});

export const retractFrame = (attemptId: string): ConversationFrame => ({
  kind: "retract",
  attempt_id: attemptId,
});

export const stateFrame = (
  head: number,
  display: ConversationDisplay,
  workPhase: WorkPhase = "none",
): ConversationFrame => ({
  kind: "state",
  head,
  display,
  work_phase: workPhase,
});

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

export interface GeneratedConversation {
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
  private readonly liveTasks: string[] = [];
  private readonly unanswered: string[] = [];

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
    this.append(userMessage(messageId));
    this.publish("thinking");
    const replyId = this.next("r");
    let attemptId = this.next("a");
    while (this.chance(0.3)) {
      this.stream(attemptId, { replyId }, this.chunks(1));
      this.frames.push(retractFrame(attemptId));
      this.retractedAttempts.push(attemptId);
      attemptId = this.next("a");
    }
    this.stream(attemptId, { replyId }, this.chunks(1));
    const replySeq = this.append(reply(replyId, attemptId));
    this.stream(attemptId, { replyId }, this.chunks(0));
    if (mayStayOpen && this.chance(0.5)) return;
    const saved = reply(replyId, attemptId, `saved ${replyId}`);
    this.frames.push(entryUpdatedFrame(replySeq, saved));
    this.append(replySettled(replyId, this.unanswered.splice(0), this.seq));
    this.publishSettled();
  }

  startWork(): void {
    const taskId = this.next("k");
    this.liveTasks.push(taskId);
    this.append(workStarted(taskId, this.seq));
    this.publish("working");
    this.stream(this.next("a"), { taskId }, this.chunks(1));
    if (!this.chance(0.4)) return;
    const approvalId = this.next("p");
    this.append(approvalRequested(taskId, approvalId));
    this.publish("awaiting_approval", "awaiting_approval");
    this.append(approvalDecided(approvalId));
    this.publish("working");
  }

  finishWork(): void {
    const [taskId] = this.liveTasks.splice(0, 1);
    this.append(workFinished(taskId));
    this.publishSettled();
  }

  notice(): void {
    this.append(notice(this.next("n")));
    this.publishSettled();
  }

  stop(): void {
    this.append(stopRequested(this.next("s")));
    for (const taskId of this.liveTasks.splice(0)) {
      this.append(workFinished(taskId, "cancelled"));
    }
    this.publish("idle");
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

  private append(entry: Entry): number {
    this.seq += 1;
    this.frames.push(entryFrame(this.seq, entry));
    return this.seq;
  }

  private publish(display: ConversationDisplay, workPhase?: WorkPhase): void {
    const phase = workPhase ?? (this.hasLiveWork ? "running" : "none");
    this.frames.push(stateFrame(this.seq, display, phase));
  }

  private publishSettled(): void {
    this.publish(this.hasLiveWork ? "working" : "idle");
  }

  private stream(attemptId: string, target: DeltaTarget, chunks: number): void {
    for (let i = 0; i < chunks; i++) {
      this.frames.push(
        textDelta(attemptId, target, `${attemptMarker(attemptId)}${i} `),
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
