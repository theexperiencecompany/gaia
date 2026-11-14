// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { TypedToolDataEntry } from "@/config/registries/toolRegistry";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";

import TextBubble from ".";

vi.mock("next/navigation", () => ({
  useParams: () => ({}),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children }: { children: ReactNode }) => <span>{children}</span>,
  usePathname: () => "/c",
  useRouter: () => ({ push: vi.fn() }),
}));

// An email thread card handed a thread with no messages throws inside its render.
const CRASHING_CARD = [
  {
    tool_name: "email_thread_data",
    data: {},
    timestamp: "2026-10-14T00:00:00Z",
  },
] as unknown as TypedToolDataEntry[];

describe("TextBubble with a card that throws while rendering", () => {
  it("keeps the streamed text and contains the crash to that card", () => {
    vi.spyOn(console, "error").mockImplementation(vi.fn());

    const props = {
      message_id: "bot-1",
      text: "Here is the streamed progress",
      bubbles: ["Here is the streamed progress"],
      tool_data: CRASHING_CARD,
      // The bubble draws the cards the server folded into its timeline.
      timeline: {
        steps: [],
        cards: CRASHING_CARD.map((card) => ({ key: card.tool_name, card })),
      },
    } as ChatBubbleBotProps;
    render(<TextBubble {...props} />);

    expect(screen.getByText("Here is the streamed progress")).toBeDefined();
    expect(screen.getByRole("alert").textContent).toContain(
      "couldn't be displayed",
    );
  });
});

const turn = (over: Partial<ChatBubbleBotProps>) =>
  ({
    message_id: "bot-1",
    text: "Looking into dentists",
    bubbles: ["Looking into dentists"],
    ...over,
  }) as ChatBubbleBotProps;

describe("a turn the user stopped", () => {
  it("says Stopped under what had streamed", () => {
    render(<TextBubble {...turn({ stopped: true })} />);

    expect(screen.getByText("Looking into dentists")).toBeDefined();
    expect(screen.getByText("Stopped")).toBeDefined();
  });

  it("says nothing extra on a turn that finished", () => {
    render(<TextBubble {...turn({})} />);

    expect(screen.queryByText("Stopped")).toBeNull();
  });

  it("leaves a failed turn to its own failure line", () => {
    render(<TextBubble {...turn({ stopped: true, error: "Provider down" })} />);

    expect(screen.queryByText("Stopped")).toBeNull();
  });
});
