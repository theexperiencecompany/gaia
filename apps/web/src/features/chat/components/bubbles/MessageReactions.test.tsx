// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import { domAnimation, LazyMotion } from "motion/react";
import { describe, expect, it } from "vitest";

import { MessageReactions } from "@/features/chat/components/bubbles/MessageReactions";

const badge = (emoji: string, by: "jev" | "chat_model") => (
  <LazyMotion features={domAnimation}>
    <MessageReactions reaction={{ emoji, by }} />
  </LazyMotion>
);

describe("MessageReactions", () => {
  it("shows the message's reaction", () => {
    render(badge("🔎", "jev"));

    expect(screen.getByRole("group", { name: "Reaction" }).textContent).toBe(
      "🔎",
    );
  });

  it("swaps the emoji in place when the chat model's pick replaces it", () => {
    const { rerender } = render(badge("🔎", "jev"));
    const shown = screen.getByRole("group", { name: "Reaction" });

    rerender(badge("👍", "chat_model"));

    const replaced = screen.getByRole("group", { name: "Reaction" });
    expect(replaced).toBe(shown);
    expect(replaced.textContent).toBe("👍");
  });
});
