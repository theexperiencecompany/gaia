// @vitest-environment jsdom
import type { TodoRunWake } from "@shared/api/generated";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TodoRunWakeIndicator } from "@/features/chat/components/bubbles/user/TodoRunWakeIndicator";

const WAKE: TodoRunWake = {
  kind: "schedule",
  trigger_names: [],
  approval_summary: null,
};

afterEach(() => {
  vi.clearAllMocks();
});

describe("what woke a tracked todo's run", () => {
  it("renders as the user's side of the run, with its label", () => {
    render(<TodoRunWakeIndicator wake={WAKE} />);

    expect(screen.getByText("Scheduled run")).toBeTruthy();
  });

  it("renders the registry's words for a triggered run", () => {
    render(
      <TodoRunWakeIndicator
        wake={{
          ...WAKE,
          kind: "trigger",
          trigger_names: ["gmail_email_sent", "gmail_new_message"],
        }}
      />,
    );

    expect(
      screen.getByText("Woke up on sent emails and on new emails"),
    ).toBeTruthy();
  });
});
