// @vitest-environment jsdom
/**
 * The onboarding question reply is a pill row of tinted icon chips plus one
 * Continue button, for both questions.
 *
 * What is pinned here: picking a chip never advances the flow on its own
 * (Q1 used to advance the moment a profession was selected), Q1 is
 * single-select while Q2 is multi-select, a picked chip is announced as
 * pressed, Continue stays disabled until there is something to submit, and
 * Q2's "Something else" is a real answer: typed text alone can submit, lands
 * in state, and un-picking the chip throws the text away.
 * The harness drives the real reducer, so "advanced" means the stage cursor
 * actually moved — not that a mock was called.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { useReducer } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { QuestionsReply } from "@/features/onboarding/components/stages/Questions";
import { questions } from "@/features/onboarding/constants";
import { initialState } from "@/features/onboarding/state/initial";
import { reducer } from "@/features/onboarding/state/reducer";
import type { OnboardingState } from "@/features/onboarding/state/types";

/** Renders the composer over the real reducer and exposes the live state. */
function renderComposer(start: OnboardingState = initialState) {
  const seen: { state: OnboardingState } = { state: start };

  function Harness() {
    const [state, dispatch] = useReducer(reducer, start);
    seen.state = state;
    return <QuestionsReply state={state} dispatch={dispatch} />;
  }

  render(<Harness />);
  return seen;
}

function chip(label: string): HTMLElement {
  return screen.getByRole("button", { name: label });
}

function pressedState(label: string): string | null {
  return chip(label).getAttribute("aria-pressed");
}

function continueButton(): HTMLButtonElement {
  return screen.getByRole("button", {
    name: /continue/i,
  }) as HTMLButtonElement;
}

describe("Q1 profession chips", () => {
  it("does not advance to Q2 when a chip is picked", () => {
    const seen = renderComposer();

    fireEvent.click(chip("Founder / CEO"));

    expect(seen.state.draftProfession).toBe("founder");
    expect(seen.state.responses).toEqual({});
    expect(seen.state.questionIndex).toBe(0);
  });

  it("advances only on Continue, submitting the picked value", () => {
    const seen = renderComposer();

    expect(continueButton().disabled).toBe(true);

    fireEvent.click(chip("Engineering"));
    expect(continueButton().disabled).toBe(false);

    fireEvent.click(continueButton());
    expect(seen.state.responses).toEqual({ profession: "engineering" });
    expect(seen.state.questionIndex).toBe(1);
  });

  it("is single-select — picking a second chip replaces the first", () => {
    renderComposer();

    fireEvent.click(chip("Sales"));
    expect(pressedState("Sales")).toBe("true");

    fireEvent.click(chip("Student"));
    expect(pressedState("Student")).toBe("true");
    expect(pressedState("Sales")).toBe("false");
  });
});

describe("Q2 needs chips", () => {
  const atQ2: OnboardingState = {
    ...initialState,
    responses: { profession: "founder" },
    questionIndex: 1,
  };

  it("is multi-select and keeps every pick pressed", () => {
    const seen = renderComposer(atQ2);

    fireEvent.click(chip("Drowning in email"));
    fireEvent.click(chip("Follow-ups slip through"));

    expect(seen.state.selectedNeeds).toEqual(["inbox", "todos"]);
    expect(pressedState("Drowning in email")).toBe("true");
    expect(pressedState("Follow-ups slip through")).toBe("true");
  });

  it("blocks Continue until at least one need is picked", () => {
    const seen = renderComposer(atQ2);

    expect(continueButton().disabled).toBe(true);

    fireEvent.click(chip("Research eats my evenings"));
    expect(continueButton().disabled).toBe(false);

    fireEvent.click(continueButton());
    expect(seen.state.questionIndex).toBe(questions.length);
  });

  it("'Something else' opens a field whose text alone can submit on Enter", () => {
    const seen = renderComposer(atQ2);

    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(chip("Something else"));
    expect(pressedState("Something else")).toBe("true");

    const field = screen.getByRole("textbox");
    fireEvent.change(field, { target: { value: "chasing invoices" } });
    expect(seen.state.otherNeed).toBe("chasing invoices");
    expect(seen.state.selectedNeeds).toEqual([]);
    expect(continueButton().disabled).toBe(false);

    fireEvent.keyDown(field, { key: "Enter" });
    expect(seen.state.questionIndex).toBe(questions.length);
  });

  it("keeps the catch-all out of the needs list and clears it when un-picked", () => {
    const seen = renderComposer(atQ2);

    fireEvent.click(chip("Something else"));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "chasing invoices" },
    });
    fireEvent.click(chip("Something else"));

    expect(screen.queryByRole("textbox")).toBeNull();
    expect(seen.state.otherNeed).toBe("");
    expect(seen.state.selectedNeeds).toEqual([]);
    expect(continueButton().disabled).toBe(true);
  });

  it("Enter does nothing while the field is blank", () => {
    const seen = renderComposer(atQ2);

    fireEvent.click(chip("Something else"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "   " } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });

    expect(seen.state.questionIndex).toBe(1);
  });
});
