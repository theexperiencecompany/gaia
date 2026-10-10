// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";

/**
 * ChatBubbleBot decides whether a bot turn renders at all and which chrome it
 * gets (avatar, memory indicator, reactions, footer). The bubble content
 * itself is TextBubble's job, so it is stubbed to a marker here.
 */

vi.mock("@/features/chat/components/bubbles/bot/TextBubble", () => ({
  default: ({ text }: { text?: string }) => (
    <div data-testid="text-bubble">{text}</div>
  ),
}));

vi.mock("@/features/chat/components/bubbles/bot/ImageBubble", () => ({
  default: () => <div data-testid="image-bubble" />,
}));

vi.mock("@/features/chat/components/bubbles/bot/BotBubbleChrome", () => ({
  BotBubbleAvatar: () => <div data-testid="bot-avatar" />,
  BotBubbleFooter: () => <div data-testid="bot-footer" />,
}));

type BubbleProps = Parameters<typeof ChatBubbleBot>[0];

function renderBubble(over: Partial<BubbleProps> = {}, children?: ReactNode) {
  const props = {
    text: "",
    message_id: "bot-1",
    ...over,
  } as ChatBubbleBotProps;
  return render(<ChatBubbleBot {...props}>{children}</ChatBubbleBot>);
}

const MEMORY = { type: "memory_stored" } as ChatBubbleBotProps["memory_data"];

describe("ChatBubbleBot visibility", () => {
  it("renders nothing while loading before any content arrives", () => {
    const { container } = renderBubble({ loading: true });
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing for an idle turn with no content", () => {
    const { container } = renderBubble();
    expect(container.innerHTML).toBe("");
  });

  it("renders the bubble while loading once text has streamed in", () => {
    const { container } = renderBubble({ loading: true, text: "hello" });
    expect(container.querySelector("#bot-1")).not.toBeNull();
    expect(screen.getByTestId("text-bubble").textContent).toBe("hello");
  });

  it("renders a tool-only turn without the text chrome", () => {
    renderBubble({
      tool_data: [
        { tool_name: "weather_data", tool_category: "weather", data: {} },
      ] as unknown as ChatBubbleBotProps["tool_data"],
    });
    expect(screen.getByTestId("text-bubble")).toBeDefined();
    expect(screen.queryByTestId("bot-avatar")).toBeNull();
    expect(screen.queryByTestId("bot-footer")).toBeNull();
  });

  it("gives a failed turn with no text the full chrome so Retry is reachable", () => {
    renderBubble({ error: "Provider down" });
    expect(screen.getByTestId("bot-avatar")).toBeDefined();
    expect(screen.getByTestId("bot-footer")).toBeDefined();
  });

  it("renders the image bubble instead of text when image data is present", () => {
    renderBubble({
      image_data: {
        url: "https://example.com/a.png",
      } as ChatBubbleBotProps["image_data"],
    });
    expect(screen.getByTestId("image-bubble")).toBeDefined();
    expect(screen.queryByTestId("text-bubble")).toBeNull();
  });

  it("hides chrome for an email-processing system conversation", () => {
    renderBubble({
      text: "processed",
      isConvoSystemGenerated: true,
      systemPurpose: "email_processing" as ChatBubbleBotProps["systemPurpose"],
    });
    expect(screen.getByTestId("text-bubble")).toBeDefined();
    expect(screen.queryByTestId("bot-avatar")).toBeNull();
    expect(screen.queryByTestId("bot-footer")).toBeNull();
  });
});

describe("ChatBubbleBot avatar", () => {
  it("shows the avatar on an ungrouped text bubble", () => {
    renderBubble({ text: "hi" });
    expect(screen.getByTestId("bot-avatar")).toBeDefined();
    expect(screen.getByTestId("bot-footer")).toBeDefined();
  });

  it("drops the avatar when the next bubble continues the group", () => {
    renderBubble({ text: "hi", isGroupedWithNext: true });
    expect(screen.queryByTestId("bot-avatar")).toBeNull();
    expect(screen.getByTestId("bot-footer")).toBeDefined();
  });

  it("drops the avatar when hideAvatar is set", () => {
    renderBubble({ text: "hi", hideAvatar: true });
    expect(screen.queryByTestId("bot-avatar")).toBeNull();
  });
});

describe("ChatBubbleBot attachments", () => {
  it("shows the memory indicator only when an opener is wired", () => {
    const { unmount } = renderBubble({ text: "hi", memory_data: MEMORY });
    expect(screen.queryByText("memory stored")).toBeNull();
    unmount();

    renderBubble({
      text: "hi",
      memory_data: MEMORY,
      onOpenMemoryModal: () => undefined,
    });
    expect(screen.getByText("memory stored")).toBeDefined();
  });

  it("renders reactions below the bubble", () => {
    renderBubble({
      text: "hi",
      reactions: [{ emoji: "👍" }] as ChatBubbleBotProps["reactions"],
    });
    expect(screen.getByText("👍")).toBeDefined();
  });

  it("renders children after the bubble", () => {
    renderBubble({ text: "hi" }, <span>trailing child</span>);
    expect(screen.getByText("trailing child")).toBeDefined();
  });
});
