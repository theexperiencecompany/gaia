// @vitest-environment jsdom
import type { AuthoredGateView, SystemGateView } from "@shared/api/generated";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const editSubscriptionGate = vi.fn();
const updateTodoOptimistic = vi.fn();

vi.mock("@/features/todo/api/todoApi", () => ({
  editSubscriptionGate: (...args: unknown[]) => editSubscriptionGate(...args),
}));

vi.mock("@/stores/todoStore", () => ({
  useTodoStore: (
    select: (state: {
      updateTodoOptimistic: typeof updateTodoOptimistic;
    }) => unknown,
  ) => select({ updateTodoOptimistic }),
}));

import { SubscriptionGateLine } from "@/features/todo/components/SubscriptionGateLine";
import { makeTodo } from "./fixtures/todo";

const openDetail = () =>
  fireEvent.click(screen.getByRole("button", { name: /only when/i }));

const BILLING = "the email is from a customer about billing";
const INVOICES = "the email is about an invoice";
const DESK_TEXT = "a real person or a real obligation is waiting on you";

const AUTHORED: AuthoredGateView = {
  kind: "authored",
  condition: BILLING,
  author: "gaia",
  enabled: true,
  display_condition: BILLING,
  enforced: false,
  recent_skips: [],
  skipped_count: 0,
};

const DESK: SystemGateView = {
  kind: "system",
  preset: "inbox_desk",
  enabled: true,
  display_condition: DESK_TEXT,
  enforced: true,
  recent_skips: [],
  skipped_count: 0,
};

describe("a tracked todo's runs-only-when line", () => {
  const saved = makeTodo("todo-1");

  beforeEach(() => {
    vi.clearAllMocks();
    editSubscriptionGate.mockResolvedValue(saved);
  });

  it("saves a rewritten rule when the user saves it", async () => {
    render(
      <SubscriptionGateLine
        todoId="todo-1"
        subscriptionId="watch-1"
        triggerName="gmail_new_message"
        gate={AUTHORED}
      />,
    );

    openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Edit rule" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Edit rule" }), {
      target: { value: `  ${INVOICES} ` },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(editSubscriptionGate).toHaveBeenCalledWith("todo-1", "watch-1", {
      condition: INVOICES,
      enabled: true,
    });
    await waitFor(() =>
      expect(updateTodoOptimistic).toHaveBeenCalledWith("todo-1", saved),
    );
  });

  it("sends nothing when the rule is left as it was", () => {
    render(
      <SubscriptionGateLine
        todoId="todo-1"
        subscriptionId="watch-1"
        triggerName="gmail_new_message"
        gate={AUTHORED}
      />,
    );

    openDetail();
    fireEvent.click(screen.getByRole("button", { name: "Edit rule" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(editSubscriptionGate).not.toHaveBeenCalled();
  });

  it("turns the gate off with enabled false alone, keeping its text", () => {
    render(
      <SubscriptionGateLine
        todoId="todo-1"
        subscriptionId="watch-1"
        triggerName="gmail_new_message"
        gate={AUTHORED}
      />,
    );

    openDetail();
    fireEvent.click(screen.getByRole("switch", { name: "Filter new mail" }));

    expect(editSubscriptionGate).toHaveBeenCalledWith("todo-1", "watch-1", {
      enabled: false,
    });
  });

  it("shows the desk's preset read only, and still lets it be turned off", () => {
    render(
      <SubscriptionGateLine
        todoId="todo-1"
        subscriptionId="watch-1"
        triggerName="gmail_new_message"
        gate={DESK}
      />,
    );

    expect(screen.getByText(`Only when ${DESK_TEXT}`)).toBeTruthy();
    openDetail();
    expect(screen.queryByRole("button", { name: "Edit rule" })).toBeNull();
    fireEvent.click(screen.getByRole("switch"));
    expect(editSubscriptionGate).toHaveBeenCalledWith("todo-1", "watch-1", {
      enabled: false,
    });
  });
});
