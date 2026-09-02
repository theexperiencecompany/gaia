import { describe, expect, it } from "vitest";

import {
  FIELD_NAMES,
  needOptions,
  OTHER_NEED_OPTION,
  professionOptions,
  questions,
} from "@/features/onboarding/constants";
import { OPTION_STYLE } from "@/features/onboarding/constants/optionStyle";
import { canSubmitNeeds, getStage } from "@/features/onboarding/state/derive";
import { initialState } from "@/features/onboarding/state/initial";
import { getMessages } from "@/features/onboarding/state/messages";
import { reducer } from "@/features/onboarding/state/reducer";
import type {
  Action,
  OnboardingState,
} from "@/features/onboarding/state/types";

function apply(state: OnboardingState, ...actions: Action[]): OnboardingState {
  return actions.reduce(reducer, state);
}

const answeredQuestions = apply(
  initialState,
  { type: "answer", field: FIELD_NAMES.PROFESSION, value: "founder" },
  { type: "toggleNeed", value: "inbox" },
  { type: "submitNeeds" },
);

describe("onboarding stage machine", () => {
  it("walks the paid-first queue in order", () => {
    const paid = true;
    expect(getStage(initialState, paid)).toBe("questions");

    let state = apply(initialState, {
      type: "answer",
      field: FIELD_NAMES.PROFESSION,
      value: "founder",
    });
    expect(getStage(state, paid)).toBe("questions");

    state = apply(state, { type: "toggleNeed", value: "inbox" });
    state = apply(state, { type: "submitNeeds" });
    expect(getStage(state, paid)).toBe("paidReveal");

    state = apply(state, { type: "ackPaidReveal" });
    expect(getStage(state, paid)).toBe("greeting");

    state = apply(state, { type: "ackGreeting" });
    expect(getStage(state, paid)).toBe("platformPick");

    state = apply(state, { type: "skipPlatforms" });
    expect(getStage(state, paid)).toBe("chat");
  });

  it("parks an unpaid user on the payment stage", () => {
    expect(getStage(answeredQuestions, false)).toBe("payment");
  });

  it("skips the payment stage entirely for an already-subscribed user", () => {
    // No payment-specific state is ever set: the stage is done the moment
    // the backend reports a subscription.
    expect(getStage(answeredQuestions, true)).toBe("paidReveal");
  });

  it("never advances past payment on an unknown plan status", () => {
    // `useIsPaid().isPaid` is false while unknown, so the queue holds.
    const acked = apply(
      answeredQuestions,
      { type: "ackPaidReveal" },
      { type: "ackGreeting" },
      { type: "skipPlatforms" },
    );
    expect(getStage(acked, false)).toBe("payment");
  });

  it("advances the platform stage when a platform is connected", () => {
    const state = apply(
      answeredQuestions,
      { type: "ackPaidReveal" },
      { type: "ackGreeting" },
      { type: "platformConnected", platform: "telegram" },
    );
    expect(state.connectedPlatform).toBe("telegram");
    expect(getStage(state, true)).toBe("chat");
  });
});

describe("Q2 multi-select", () => {
  it("blocks submission until at least one need is picked", () => {
    const afterQ1 = apply(initialState, {
      type: "answer",
      field: FIELD_NAMES.PROFESSION,
      value: "founder",
    });
    expect(canSubmitNeeds(afterQ1)).toBe(false);

    const attempted = apply(afterQ1, { type: "submitNeeds" });
    expect(attempted.questionIndex).toBeLessThan(questions.length);
    expect(getStage(attempted, true)).toBe("questions");
  });

  it("toggles a need off again", () => {
    const state = apply(
      initialState,
      { type: "toggleNeed", value: "inbox" },
      { type: "toggleNeed", value: "todos" },
      { type: "toggleNeed", value: "inbox" },
    );
    expect(state.selectedNeeds).toEqual(["todos"]);
  });

  it("serializes needs as backend OnboardingNeed values", () => {
    const state = apply(
      initialState,
      { type: "toggleNeed", value: "automation" },
      { type: "toggleNeed", value: "memory" },
    );
    // Order is selection order, and every value is a known option.
    expect(state.selectedNeeds).toEqual(["automation", "memory"]);
    for (const need of state.selectedNeeds) {
      expect(needOptions.some((o) => o.value === need)).toBe(true);
    }
  });

  it("has an icon and a tint for every option the chips render", () => {
    // The chips destructure `OPTION_STYLE[value]` unconditionally — a missing
    // entry is a render crash, not a blank chip.
    for (const option of [
      ...professionOptions,
      ...needOptions,
      OTHER_NEED_OPTION,
    ]) {
      const style = OPTION_STYLE[option.value];
      expect(style?.icon).toBeTypeOf("function");
      expect(style?.tint.idle).toMatch(/^bg-\S+ text-\S+$/);
      expect(style?.tint.active).toMatch(/^bg-\S+ text-\S+$/);
    }
  });

  it("offers seven backend needs and never the catch-all", () => {
    // `reach` stays in the backend enum for users who picked it before the
    // platform step took it over; it is no longer a chip.
    expect(needOptions.map((o) => o.value)).toEqual([
      "inbox",
      "calendar",
      "briefings",
      "todos",
      "memory",
      "research",
      "automation",
    ]);
    expect(needOptions.some((o) => o.value === OTHER_NEED_OPTION.value)).toBe(
      false,
    );
  });

  it("can submit on typed words alone, but not on blank ones", () => {
    const typed = apply(initialState, {
      type: "setOtherNeed",
      value: "chasing invoices",
    });
    expect(canSubmitNeeds(typed)).toBe(true);
    expect(canSubmitNeeds({ ...typed, otherNeed: "   " })).toBe(false);
  });
});

describe("transcript", () => {
  it("shows the profession label and the selected need labels", () => {
    const messages = getMessages({
      responses: answeredQuestions.responses,
      questionIndex: answeredQuestions.questionIndex,
      selectedNeeds: answeredQuestions.selectedNeeds,
      otherNeed: "",
    });
    const contents = messages.map((m) => m.content);
    expect(contents).toContain("Founder / CEO");
    expect(contents).toContain("Drowning in email");
  });

  it("acknowledges the job in Q2's opener and appends the typed need", () => {
    const contents = getMessages({
      responses: answeredQuestions.responses,
      questionIndex: answeredQuestions.questionIndex,
      selectedNeeds: answeredQuestions.selectedNeeds,
      otherNeed: "chasing invoices",
    }).map((m) => m.content);
    expect(contents.some((c) => c.startsWith("Founder, got it."))).toBe(true);
    expect(contents).toContain("Drowning in email, chasing invoices");
  });

  it("does not render the Q2 answer before it is submitted", () => {
    const state = apply(
      initialState,
      { type: "answer", field: FIELD_NAMES.PROFESSION, value: "founder" },
      { type: "toggleNeed", value: "inbox" },
    );
    const contents = getMessages({
      responses: state.responses,
      questionIndex: state.questionIndex,
      selectedNeeds: state.selectedNeeds,
      otherNeed: "",
    }).map((m) => m.content);
    expect(contents).not.toContain("Drowning in email");
  });
});
