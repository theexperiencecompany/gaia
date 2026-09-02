// @vitest-environment jsdom
/**
 * The onboarding question composer is a pill row of emoji chips plus one
 * Continue button, for both questions.
 *
 * What is pinned here: picking a chip never advances the flow on its own
 * (Q1 used to advance the moment a profession was selected), Q1 is
 * single-select while Q2 is multi-select, a picked chip is announced as
 * pressed, and Continue stays disabled until there is something to submit.
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

    fireEvent.click(chip("Manage my inbox"));
    fireEvent.click(chip("Track my todos"));

    expect(seen.state.selectedNeeds).toEqual(["inbox", "todos"]);
    expect(pressedState("Manage my inbox")).toBe("true");
    expect(pressedState("Track my todos")).toBe("true");
  });

  it("blocks Continue until at least one need is picked", () => {
    const seen = renderComposer(atQ2);

    expect(continueButton().disabled).toBe(true);

    fireEvent.click(chip("Do research"));
    expect(continueButton().disabled).toBe(false);

    fireEvent.click(continueButton());
    expect(seen.state.questionIndex).toBe(questions.length);
  });
});
