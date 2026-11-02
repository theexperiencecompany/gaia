// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
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

const turn = (over: Partial<ChatBubbleBotProps>) =>
  ({
    message_id: "bot-1",
    text: "Looking into dentists",
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
