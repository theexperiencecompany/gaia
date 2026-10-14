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

// A calendar card handed a non-array payload throws inside its render.
const CRASHING_CARD = [
  {
    tool_name: "calendar_options",
    data: "not-a-list",
    timestamp: "2026-10-14T00:00:00Z",
  },
] as unknown as TypedToolDataEntry[];

describe("TextBubble with a card that throws while rendering", () => {
  it("keeps the streamed text and contains the crash to that card", () => {
    vi.spyOn(console, "error").mockImplementation(vi.fn());

    const props = {
      message_id: "bot-1",
      text: "Here is the streamed progress",
      tool_data: CRASHING_CARD,
    } as ChatBubbleBotProps;
    render(<TextBubble {...props} />);

    expect(screen.getByText("Here is the streamed progress")).toBeDefined();
    expect(screen.getByRole("alert").textContent).toContain(
      "couldn't be displayed",
    );
  });
});
