// @vitest-environment jsdom
//
// A page load syncs every stale conversation at once. Each one landing as its own
// store write re-rendered the sidebar per write, and the sidebar's accordion effect
// set state on every one of those commits: past 50 in a row React logs
// "Maximum update depth exceeded" (live run 2, 26 conversations).
import { replyItem, userItem } from "@shared/conversation/testing";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ChatsList from "@/components/layout/sidebar/ChatsList";
import {
  type Conversation,
  chatApi,
  type SyncedConversation,
} from "@/features/chat/api/chatApi";
import { useLiveConversationStore } from "@/features/chat/live/liveConversationStore";
import type { IConversation } from "@/lib/db/chatDb";
import { batchSyncConversations } from "@/services/syncService";
import { useChatStore, useChatStoreSync } from "@/stores/chatStore";

const CONVERSATIONS = 26;
const { rows } = vi.hoisted(() => ({
  rows: new Map<string, IConversation>(),
}));
// Now, so every conversation lands in the sidebar's "Today" section.
const AT = new Date().toISOString();

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: {
    fetchConversations: vi.fn(),
    batchSyncConversations: vi.fn(),
    markAsRead: vi.fn(),
  },
}));

vi.mock("@/lib/db/chatDb", async () => {
  const { dbEventEmitter } =
    await vi.importActual<typeof import("@/lib/db/chatDb")>("@/lib/db/chatDb");
  // IndexedDB answers in a later task, so each conversation's writes land in their own commit.
  const idbTask = () => new Promise((resolve) => setTimeout(resolve, 0));
  return {
    dbEventEmitter,
    db: {
      getAllConversations: vi.fn(async () => [...rows.values()]),
      getConversation: vi.fn(async (id: string) => rows.get(id)),
      getConversationLog: vi.fn(async () => {
        await idbTask();
        return undefined;
      }),
      putConversationLog: vi.fn(async () => undefined),
      deleteConversationsAndLogsBulk: vi.fn(async () => undefined),
      putConversation: vi.fn(async (conversation: IConversation) => {
        await idbTask();
        const existed = rows.has(conversation.id);
        rows.set(conversation.id, conversation);
        if (existed) dbEventEmitter.emitConversationUpdated(conversation);
        else dbEventEmitter.emitConversationAdded(conversation);
        return conversation.id;
      }),
      putConversationsBulk: vi.fn(async (conversations: IConversation[]) => {
        await idbTask();
        for (const conversation of conversations) {
          rows.set(conversation.id, conversation);
        }
        dbEventEmitter.emitConversationsUpsertedBulk(conversations);
        return conversations.map((conversation) => conversation.id);
      }),
    },
  };
});

vi.mock("@/features/chat/hooks/useInfiniteConversations", () => ({
  useInfiniteConversations: () => ({
    loadMoreConversations: vi.fn(),
    isLoadingMore: false,
    hasMore: false,
    totalPages: 1,
  }),
}));

vi.mock("@/hooks/useBackgroundSync", () => ({
  useSyncStatus: () => ({ initialSyncCompleted: true, syncError: null }),
}));

vi.mock("@/components/layout/sidebar/ChatTab", () => ({
  ChatTab: ({ name }: { name: string }) => <div>{name}</div>,
}));

const ids = Array.from({ length: CONVERSATIONS }, (_, i) => `conv-${i}`);

const row = (id: string) => ({
  conversation_id: id,
  description: `chat ${id}`,
  starred: null,
  is_system_generated: null,
  system_purpose: null,
  is_unread: null,
  source: null,
  awaiting_approval: false,
  createdAt: AT,
  updatedAt: AT,
});

const listed = (id: string): Conversation => ({ ...row(id), user_id: "u1" });

const synced = (id: string, updatedAt = AT): SyncedConversation => ({
  ...row(id),
  updatedAt,
  todo_id: null,
  listed: true,
  artifacts: [],
  items: [userItem(`${id}-u`, 1), replyItem(`${id}-r`, 2, "hello")],
  state: { kind: "state", head: 2, display: "idle", work: [] },
  has_older: false,
  cursor: null,
});

function SidebarWithStoreSync() {
  useChatStoreSync();
  return <ChatsList />;
}

describe("a page-load sync of many conversations", () => {
  beforeEach(() => {
    rows.clear();
    useChatStore.setState({ conversations: [], artifactsByConversation: {} });
    useLiveConversationStore.setState({ conversations: {} });
    vi.mocked(chatApi.fetchConversations).mockResolvedValue({
      conversations: ids.map(listed),
      total: CONVERSATIONS,
      page: 1,
      limit: 50,
      total_pages: 1,
    });
    vi.mocked(chatApi.batchSyncConversations).mockResolvedValue({
      conversations: ids.map((id) => synced(id)),
      missing: [],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);
  });

  // Outside act, as in the browser: act would fold the burst into one commit and hide it.
  it("renders the sidebar without an update-depth loop", async () => {
    const consoleError = vi.spyOn(console, "error");
    render(<SidebarWithStoreSync />);
    Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", false);

    await batchSyncConversations();

    await waitFor(() =>
      expect(screen.getAllByText(/^chat conv-/)).toHaveLength(CONVERSATIONS),
    );
    const depthErrors = consoleError.mock.calls.filter((args) =>
      args.some((arg) => String(arg).includes("Maximum update depth")),
    );
    expect(depthErrors).toEqual([]);
  });

  it("lands every synced conversation in one write per store", async () => {
    const liveWrites = vi.fn();
    const listWrites = vi.fn();
    const unsubscribeLive = useLiveConversationStore.subscribe(liveWrites);
    const unsubscribeList = useChatStore.subscribe((state, previous) => {
      if (state.conversations !== previous.conversations) listWrites();
    });
    render(<SidebarWithStoreSync />);

    await act(async () => {
      await batchSyncConversations();
    });
    unsubscribeLive();
    unsubscribeList();

    expect(liveWrites).toHaveBeenCalledTimes(1);
    expect(listWrites).toHaveBeenCalledTimes(1);
    expect(
      Object.keys(useLiveConversationStore.getState().conversations),
    ).toHaveLength(CONVERSATIONS);
  });

  it("keeps a section the user closed closed when a later sync updates a conversation", async () => {
    render(<SidebarWithStoreSync />);
    await act(async () => {
      await batchSyncConversations();
    });

    const today = () => screen.getByRole("button", { name: /^Today/ });
    fireEvent.click(today());
    expect(today().getAttribute("aria-expanded")).toBe("false");

    const later = new Date(Date.now() + 60_000).toISOString();
    vi.mocked(chatApi.fetchConversations).mockResolvedValue({
      conversations: [{ ...listed("conv-0"), updatedAt: later }],
      total: 1,
      page: 1,
      limit: 50,
      total_pages: 1,
    });
    vi.mocked(chatApi.batchSyncConversations).mockResolvedValue({
      conversations: [synced("conv-0", later)],
      missing: [],
    });
    await act(async () => {
      await batchSyncConversations();
    });

    expect(rows.get("conv-0")).toMatchObject({ updatedAt: new Date(later) });
    expect(today().getAttribute("aria-expanded")).toBe("false");
  });
});
