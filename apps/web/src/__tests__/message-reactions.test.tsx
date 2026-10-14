// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MessageReaction } from "@/config/registries/baseMessageRegistry";
import { MessageReactions } from "@/features/chat/components/bubbles/MessageReactions";

const reaction = (emoji: string) => ({ emoji }) as MessageReaction;

describe("MessageReactions", () => {
  it("renders nothing without reactions", () => {
    const { container } = render(<MessageReactions reactions={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows each distinct emoji once, with no count for a single reaction", () => {
    render(<MessageReactions reactions={[reaction("👍"), reaction("❤️")]} />);
    expect(screen.getByLabelText("Reactions")).toBeDefined();
    expect(screen.getByText("👍")).toBeDefined();
    expect(screen.getByText("❤️")).toBeDefined();
    expect(screen.queryByText("1")).toBeNull();
  });

  it("collapses repeated emoji into one with a count", () => {
    render(<MessageReactions reactions={[reaction("🔥"), reaction("🔥")]} />);
    expect(screen.getAllByText("🔥")).toHaveLength(1);
    expect(screen.getByText("2")).toBeDefined();
  });
});
