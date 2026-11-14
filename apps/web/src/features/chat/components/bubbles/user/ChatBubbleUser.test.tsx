// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BASE_MESSAGE_SCHEMA } from "@/config/registries/baseMessageRegistry";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ profilePicture: "" }),
}));

vi.mock("@/features/chat/components/interface/MarkdownRenderer", () => ({
  default: ({ content }: { content: string }) => <span>{content}</span>,
}));

vi.mock("@/components/ui/avatar", () => ({
  Avatar: () => <div data-testid="user-avatar" />,
  AvatarImage: () => null,
  AvatarFallback: () => null,
}));

vi.mock("./ChatBubbleUserFooter", () => ({
  ChatBubbleUserFooter: () => <div data-testid="user-footer" />,
}));

type BubbleProps = Parameters<typeof ChatBubbleUser>[0];

function renderBubble(over: Partial<BubbleProps> = {}) {
  const props: BubbleProps = {
    ...BASE_MESSAGE_SCHEMA,
    text: "whats 2+2",
    message_id: "u1",
    ...over,
  };
  return render(<ChatBubbleUser {...props} />);
}

const bubbleOf = (text: string) =>
  screen.getByText(text).closest(".imessage-bubble");

describe("ChatBubbleUser grouping", () => {
  it("gives a message on its own the avatar, tail and footer", () => {
    renderBubble();
    expect(screen.getByTestId("user-avatar")).toBeTruthy();
    expect(screen.getByTestId("user-footer")).toBeTruthy();
    expect(bubbleOf("whats 2+2")?.className).not.toContain(
      "imessage-grouped-first",
    );
  });

  it("drops the avatar, tail and footer from a message followed by another", () => {
    renderBubble({ grouping: { withPrev: false, withNext: true } });
    expect(screen.queryByTestId("user-avatar")).toBeNull();
    expect(screen.queryByTestId("user-footer")).toBeNull();
    expect(bubbleOf("whats 2+2")?.className).toContain(
      "imessage-grouped-first",
    );
  });

  it("sits tight under the message before it", () => {
    const { container } = renderBubble({
      grouping: { withPrev: true, withNext: false },
    });
    expect((container.firstChild as HTMLElement).className).toContain("mt-1.5");
  });

  it("keeps the footer of a failed message inside a group, so Retry stays reachable", () => {
    renderBubble({
      grouping: { withPrev: false, withNext: true },
      failed: true,
    });
    expect(screen.getByTestId("user-footer")).toBeTruthy();
  });
});
