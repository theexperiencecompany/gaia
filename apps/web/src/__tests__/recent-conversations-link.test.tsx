// @vitest-environment jsdom
/** Regression: the dashboard's recent chats pushed /chat/<id>, a route that does not exist, so every click was a 404. */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/features/chat/hooks/useConversationList", () => ({
  useConversationList: () => ({
    conversations: [
      {
        conversation_id: "conv-42",
        title: "Quarterly plan",
        description: "",
        starred: false,
        createdAt: "2026-11-01T10:00:00Z",
        updatedAt: "2026-11-01T10:00:00Z",
      },
    ],
  }),
}));

vi.mock("@/hooks/useBackgroundSync", () => ({
  useSyncStatus: () => ({ initialSyncCompleted: true, syncError: null }),
}));

vi.mock("@/stores/composerStore", () => ({
  useAppendToInput: () => vi.fn(),
}));

import RecentConversationsView from "@/features/chat/components/RecentConversationsView";

describe("RecentConversationsView", () => {
  it("opens a conversation on the chat route", () => {
    render(<RecentConversationsView />);

    fireEvent.click(screen.getByText("Quarterly plan"));

    expect(push).toHaveBeenCalledWith("/c/conv-42");
  });
});
