import { create } from "zustand";
import { devtools } from "zustand/middleware";

import { useChatStore } from "@/stores/chatStore";
import {
  getRandomThinkingMessage,
  getRelevantThinkingMessage,
} from "@/utils/playfulThinking";

export interface ToolInfo {
  toolName?: string;
  toolCategory?: string;
  integrationName?: string;
  iconUrl?: string;
  showCategory?: boolean;
}

/**
 * Turn lifecycle phases. A session entry exists only while a turn is active —
 * absence means idle. Terminal states (done/error/aborted) remove the entry.
 *
 * - connecting: send fired, SSE not yet delivering events
 * - streaming: SSE open (covers the background-executor tail that streams over
 *   the same connection after `main_response_complete`)
 * - awaiting_executor: SSE closed but a delegated background executor still owes
 *   its result message (delivered via the `conversation.new_message` WebSocket)
 */
export type TurnPhase = "connecting" | "streaming" | "awaiting_executor";

export interface TurnUiState {
  phase: TurnPhase;
  /** Loading indicator visibility — toggles within a phase (e.g. off at
   *  main_response_complete, back on when executor events resume). */
  spinnerActive: boolean;
  /** True from send until `main_response_complete` — the window where the
   *  composer is locked and sends are queued. */
  composerLocked: boolean;
  loadingText: string;
  loadingTextKey: number;
  toolInfo?: ToolInfo;
}

/** Loading UI owned by non-turn flows (voice agent, file upload). */
interface AuxLoadingState {
  active: boolean;
  text: string;
  key: number;
  toolInfo?: ToolInfo;
}

interface StreamState {
  /** Active turn sessions keyed by conversation id (or a pending key for a
   *  brand-new conversation until the backend assigns the real id). */
  sessions: Record<string, TurnUiState>;
  /** Pending-key of the in-flight new-conversation turn, if any. Lets "active
   *  conversation" selectors resolve a turn that has no conversation id yet. */
  pendingNewConversationKey: string | null;
  auxLoading: AuxLoadingState | null;
  /** Abort persistence in flight — background sync must not race it. */
  pendingSaveCount: number;
}

interface StreamActions {
  startSession: (key: string, userMessage?: string) => void;
  updateSession: (key: string, updates: Partial<TurnUiState>) => void;
  rekeySession: (oldKey: string, newKey: string) => void;
  endSession: (key: string) => void;
  setSessionLoadingText: (
    key: string,
    text: string,
    toolInfo?: ToolInfo,
  ) => void;
  resetSessionLoadingText: (key: string) => void;
  setAuxLoading: (active: boolean, text?: string, toolInfo?: ToolInfo) => void;
  /** Overwrite a session from an external snapshot (desktop popup mirror). */
  mirrorSession: (key: string, session: TurnUiState | null) => void;
  beginPendingSave: () => void;
  endPendingSave: () => void;
}

type StreamStore = StreamState & StreamActions;

export const useStreamStore = create<StreamStore>()(
  devtools(
    (set) => ({
      sessions: {},
      pendingNewConversationKey: null,
      auxLoading: null,
      pendingSaveCount: 0,

      startSession: (key, userMessage) =>
        set(
          (state) => ({
            sessions: {
              ...state.sessions,
              [key]: {
                phase: "connecting" as const,
                spinnerActive: true,
                composerLocked: true,
                loadingText: userMessage?.trim()
                  ? getRelevantThinkingMessage(userMessage)
                  : getRandomThinkingMessage(),
                loadingTextKey: (state.sessions[key]?.loadingTextKey ?? 0) + 1,
                toolInfo: undefined,
              },
            },
            pendingNewConversationKey: key.startsWith(PENDING_KEY_PREFIX)
              ? key
              : state.pendingNewConversationKey,
          }),
          false,
          "startSession",
        ),

      updateSession: (key, updates) =>
        set(
          (state) => {
            const existing = state.sessions[key];
            if (!existing) return state;
            return {
              sessions: {
                ...state.sessions,
                [key]: { ...existing, ...updates },
              },
            };
          },
          false,
          "updateSession",
        ),

      rekeySession: (oldKey, newKey) =>
        set(
          (state) => {
            const existing = state.sessions[oldKey];
            if (!existing) return state;
            const { [oldKey]: _removed, ...rest } = state.sessions;
            return {
              sessions: { ...rest, [newKey]: existing },
              pendingNewConversationKey:
                state.pendingNewConversationKey === oldKey
                  ? null
                  : state.pendingNewConversationKey,
            };
          },
          false,
          "rekeySession",
        ),

      endSession: (key) =>
        set(
          (state) => {
            if (!state.sessions[key]) return state;
            const { [key]: _removed, ...rest } = state.sessions;
            return {
              sessions: rest,
              pendingNewConversationKey:
                state.pendingNewConversationKey === key
                  ? null
                  : state.pendingNewConversationKey,
            };
          },
          false,
          "endSession",
        ),

      setSessionLoadingText: (key, text, toolInfo) =>
        set(
          (state) => {
            const existing = state.sessions[key];
            if (!existing) return state;
            return {
              sessions: {
                ...state.sessions,
                [key]: {
                  ...existing,
                  loadingText: text,
                  toolInfo,
                  loadingTextKey: existing.loadingTextKey + 1,
                },
              },
            };
          },
          false,
          "setSessionLoadingText",
        ),

      resetSessionLoadingText: (key) =>
        set(
          (state) => {
            const existing = state.sessions[key];
            if (!existing) return state;
            return {
              sessions: {
                ...state.sessions,
                [key]: {
                  ...existing,
                  loadingText: getRandomThinkingMessage(),
                  toolInfo: undefined,
                  loadingTextKey: existing.loadingTextKey + 1,
                },
              },
            };
          },
          false,
          "resetSessionLoadingText",
        ),

      setAuxLoading: (active, text, toolInfo) =>
        set(
          (state) => ({
            auxLoading: active
              ? {
                  active: true,
                  text: text ?? getRandomThinkingMessage(),
                  key: (state.auxLoading?.key ?? 0) + 1,
                  toolInfo,
                }
              : null,
          }),
          false,
          "setAuxLoading",
        ),

      mirrorSession: (key, session) =>
        set(
          (state) => {
            if (!session) {
              if (!state.sessions[key]) return state;
              const { [key]: _removed, ...rest } = state.sessions;
              return { sessions: rest };
            }
            const existing = state.sessions[key];
            return {
              sessions: {
                ...state.sessions,
                [key]: {
                  ...session,
                  // Bump the animation key only when the text changes, so the
                  // throttled mirror doesn't remount the indicator every tick.
                  loadingTextKey:
                    existing && existing.loadingText === session.loadingText
                      ? existing.loadingTextKey
                      : (existing?.loadingTextKey ?? 0) + 1,
                },
              },
            };
          },
          false,
          "mirrorSession",
        ),

      beginPendingSave: () =>
        set(
          (state) => ({ pendingSaveCount: state.pendingSaveCount + 1 }),
          false,
          "beginPendingSave",
        ),

      endPendingSave: () =>
        set(
          (state) => ({
            pendingSaveCount: Math.max(0, state.pendingSaveCount - 1),
          }),
          false,
          "endPendingSave",
        ),
    }),
    { name: "stream-store" },
  ),
);

/** Non-hook check: does this conversation have a live (SSE-open) turn? */
export const isConversationStreamingNow = (conversationId: string): boolean => {
  const session = useStreamStore.getState().sessions[conversationId];
  return session != null && session.phase !== "awaiting_executor";
};

/** Non-hook check: is any turn currently streaming (any conversation)? */
export const hasAnyLiveTurn = (): boolean =>
  Object.values(useStreamStore.getState().sessions).some(
    (session) => session.phase !== "awaiting_executor",
  );

/**
 * True when background sync must not touch this conversation: an abort save is
 * being persisted, or a live turn is streaming into it.
 */
export const shouldBlockSyncForConversation = (
  conversationId: string,
): boolean => {
  if (useStreamStore.getState().pendingSaveCount > 0) return true;
  return isConversationStreamingNow(conversationId);
};

export const PENDING_KEY_PREFIX = "pending:";

// ── Selectors ────────────────────────────────────────────────────────────────

/** Key of the turn relevant to the currently-viewed conversation. */
const useActiveTurnKey = (): string | null => {
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );
  const pendingKey = useStreamStore((state) => state.pendingNewConversationKey);
  return activeConversationId ?? pendingKey;
};

const useActiveTurn = (): TurnUiState | null => {
  const key = useActiveTurnKey();
  return useStreamStore((state) =>
    key ? (state.sessions[key] ?? null) : null,
  );
};

/** Loading indicator state for the active conversation: turn spinner, the
 *  executor-await bridge, or auxiliary (voice/upload) loading. */
export const useActiveLoading = (): {
  isLoading: boolean;
  loadingText: string;
  loadingTextKey: number;
  toolInfo?: ToolInfo;
} => {
  const turn = useActiveTurn();
  const aux = useStreamStore((state) => state.auxLoading);

  if (turn && (turn.spinnerActive || turn.phase === "awaiting_executor")) {
    return {
      isLoading: true,
      loadingText: turn.loadingText,
      loadingTextKey: turn.loadingTextKey,
      toolInfo: turn.toolInfo,
    };
  }
  if (aux?.active) {
    return {
      isLoading: true,
      loadingText: aux.text,
      loadingTextKey: aux.key,
      toolInfo: aux.toolInfo,
    };
  }
  return {
    isLoading: false,
    loadingText: turn?.loadingText ?? "",
    loadingTextKey: turn?.loadingTextKey ?? 0,
    toolInfo: undefined,
  };
};

/** True while the active conversation's composer must queue sends. */
export const useActiveComposerLocked = (): boolean => {
  const turn = useActiveTurn();
  return turn != null && turn.phase !== "awaiting_executor";
};

/** True only while the comms agent produces its INITIAL response — from send
 *  until `main_response_complete`. Narrower than useActiveComposerLocked:
 *  tool/attachment buttons re-enable here while queueing stays on. */
export const useIsInitialResponseStreaming = (): boolean => {
  const turn = useActiveTurn();
  return turn?.composerLocked ?? false;
};

export const useIsConversationStreaming = (
  conversationId: string | null,
): boolean =>
  useStreamStore((state) => {
    if (!conversationId) return false;
    const session = state.sessions[conversationId];
    return session != null && session.phase !== "awaiting_executor";
  });

export const useIsAwaitingExecutor = (conversationId: string | null): boolean =>
  useStreamStore((state) =>
    conversationId
      ? state.sessions[conversationId]?.phase === "awaiting_executor"
      : false,
  );
