// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { chatApi } from "@/features/chat/api/chatApi";
import { useStreamResume } from "@/features/chat/hooks/useStreamResume";
import { turnManager } from "@/features/chat/stream/turnManager";
import { db } from "@/lib/db/chatDb";
import { applySyncedConversation } from "@/services/syncService";

vi.mock("@/features/chat/api/chatApi", () => ({
  chatApi: { batchSyncConversations: vi.fn() },
}));
vi.mock("@/features/chat/stream/turnManager", () => ({
  turnManager: { resumeIfActive: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock("@/lib/db/chatDb", () => ({ db: { getConversation: vi.fn() } }));
vi.mock("@/services/syncService", () => ({
  applySyncedConversation: vi.fn(),
}));

const CACHED_AT = new Date("2026-01-01T00:00:00Z");

afterEach(() => {
  vi.clearAllMocks();
});

describe("opening a chat that is already cached", () => {
  it("asks only for what changed since the cached copy, and still re-attaches to a live turn", async () => {
    vi.mocked(db.getConversation).mockResolvedValue({
      id: "bot-dm",
      title: "WhatsApp Chat",
      createdAt: CACHED_AT,
      updatedAt: CACHED_AT,
    });
    vi.mocked(chatApi.batchSyncConversations).mockResolvedValue({
      conversations: [],
      missing: [],
      active_streams: { "bot-dm": "stream-1" },
    });

    renderHook(() => useStreamResume("bot-dm"));

    await waitFor(() =>
      expect(turnManager.resumeIfActive).toHaveBeenCalledWith(
        "bot-dm",
        "stream-1",
      ),
    );
    expect(chatApi.batchSyncConversations).toHaveBeenCalledWith([
      { conversation_id: "bot-dm", last_updated: CACHED_AT.toISOString() },
    ]);
    expect(applySyncedConversation).not.toHaveBeenCalled();
  });

  it("fetches the full chat when nothing is cached yet", async () => {
    vi.mocked(db.getConversation).mockResolvedValue(undefined);
    vi.mocked(chatApi.batchSyncConversations).mockResolvedValue({
      conversations: [],
      missing: ["new-chat"],
      active_streams: {},
    });

    renderHook(() => useStreamResume("new-chat"));

    await waitFor(() =>
      expect(turnManager.resumeIfActive).toHaveBeenCalledWith("new-chat", null),
    );
    expect(chatApi.batchSyncConversations).toHaveBeenCalledWith([
      { conversation_id: "new-chat", last_updated: undefined },
    ]);
  });

  it("fetches the full chat, and still resumes, when the cached timestamp is invalid", async () => {
    vi.mocked(db.getConversation).mockResolvedValue({
      id: "legacy-chat",
      title: "Legacy",
      createdAt: new Date("not a date"),
      updatedAt: new Date("not a date"),
    });
    vi.mocked(chatApi.batchSyncConversations).mockResolvedValue({
      conversations: [],
      missing: [],
      active_streams: { "legacy-chat": "stream-9" },
    });

    renderHook(() => useStreamResume("legacy-chat"));

    await waitFor(() =>
      expect(turnManager.resumeIfActive).toHaveBeenCalledWith(
        "legacy-chat",
        "stream-9",
      ),
    );
    expect(chatApi.batchSyncConversations).toHaveBeenCalledWith([
      { conversation_id: "legacy-chat", last_updated: undefined },
    ]);
  });
});
