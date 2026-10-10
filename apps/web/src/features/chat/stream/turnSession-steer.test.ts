/**
 * A steer shares its conversation's session slot but owns none of it.
 *
 * The slot drives the main turn's UI — spinner, loading label, approval
 * indicator. A steer that writes to it is writing over a turn that is still
 * streaming, so every writer has to be guarded; these tests pin the one that
 * was not.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const sessions: Record<string, { awaitingApproval: boolean }> = {};
// Applies the patch like the real store does, so asserting the slot's end state
// is a claim about what production wrote — against a bare mock it would hold
// whatever the test itself put there, no matter what the code did.
const updateSession = vi.fn(
  (id: string, patch: Partial<{ awaitingApproval: boolean }>) => {
    sessions[id] = { ...sessions[id], ...patch };
  },
);

vi.mock("@/stores/streamStore", () => ({
  PENDING_KEY_PREFIX: "pending:",
  useStreamStore: {
    getState: () => ({
      sessions,
      updateSession,
      startSession: vi.fn(),
      endSession: vi.fn(),
      resetSessionLoadingText: vi.fn(),
      setSessionLoadingText: vi.fn(),
    }),
  },
}));
vi.mock("@/lib/db/chatDb", () => ({
  db: {},
  dbEventEmitter: { on: vi.fn(), off: vi.fn() },
}));
vi.mock("@/stores/chatStore", () => ({
  useChatStore: Object.assign(vi.fn(), { getState: vi.fn(() => ({})) }),
}));
vi.mock("@/stores/composerStore", () => ({
  useComposerStore: Object.assign(vi.fn(), { getState: vi.fn(() => ({})) }),
}));
vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: {},
  DuplicateTurnError: class extends Error {},
  RateLimitError: class extends Error {},
}));
vi.mock("@/services/syncService", () => ({ syncSingleConversation: vi.fn() }));
vi.mock("@/lib/toast", () => ({ toast: { error: vi.fn() } }));
vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: {},
  trackEvent: vi.fn(),
}));
vi.mock("@/features/chat/stream/unread", () => ({
  isViewingConversation: () => true,
  markConversationUnread: vi.fn(),
}));

import { TurnSession } from "@/features/chat/stream/turnSession";
import type { SendArgs } from "@/features/chat/stream/types";

const CONV = "conv-1";

const sendArgs = (): SendArgs => ({
  inputText: "and book the flight",
  userMessage: {
    type: "user",
    response: "and book the flight",
    date: new Date().toISOString(),
    message_id: "msg-1",
  },
  options: {
    fileData: [],
    selectedTool: null,
    toolCategory: null,
    selectedWorkflow: null,
    selectedCalendarEvent: null,
    optimisticUserId: "opt-1",
    replyToMessage: null,
    conversationId: CONV,
    isOnboardingDemo: false,
  },
});

/** `handleApprovalFrame` is private; the SSE plumbing that reaches it is not
 *  what these tests are about. */
const feedApproval = (
  session: TurnSession,
  approval: { approval_id: string; status: string },
): void => {
  (
    session as unknown as {
      handleApprovalFrame: (a: unknown) => void;
    }
  ).handleApprovalFrame(approval);
};

const build = (steering: boolean): TurnSession =>
  new TurnSession(
    steering ? `${CONV}:steer:1` : CONV,
    sendArgs(),
    { onEnd: vi.fn(), onRekey: vi.fn() },
    { steering },
  );

describe("a steer never writes the conversation's approval state", () => {
  beforeEach(() => {
    updateSession.mockClear();
    sessions[CONV] = { awaitingApproval: true };
  });

  it("leaves a main turn parked on an approval alone", () => {
    // BUG: a steer resolves its own gated tool and cleared awaitingApproval on
    // the shared slot, so the "Waiting for your approval" indicator vanished
    // while the main turn was still genuinely blocked on the user.
    feedApproval(build(true), { approval_id: "a-1", status: "approved" });

    expect(updateSession).not.toHaveBeenCalled();
    expect(sessions[CONV].awaitingApproval).toBe(true);
  });

  it("still lets the main turn drive its own approval state", () => {
    sessions[CONV] = { awaitingApproval: false };

    feedApproval(build(false), { approval_id: "a-1", status: "pending" });

    expect(updateSession).toHaveBeenCalledWith(CONV, {
      awaitingApproval: true,
    });
    expect(sessions[CONV].awaitingApproval).toBe(true);
  });
});
