/**
 * Q2 is "pick up to three". The cap lives in the reducer, not only in the chip
 * styling, so a stale chip or a double tap can never submit one past it.
 */

import { describe, expect, it } from "vitest";

import { NEEDS_MAX_SELECTION } from "@/features/onboarding/constants";
import { initialState } from "@/features/onboarding/state/initial";
import { reducer } from "@/features/onboarding/state/reducer";

describe("Q2 pick cap", () => {
  it("ignores a pick past the cap and still allows un-picking", () => {
    let state = initialState;
    for (const value of ["inbox", "calendar", "mornings", "reminders"]) {
      state = reducer(state, { type: "toggleNeed", value });
    }
    expect(state.selectedNeeds).toEqual(["inbox", "calendar", "mornings"]);
    expect(state.selectedNeeds.length).toBe(NEEDS_MAX_SELECTION);

    state = reducer(state, { type: "toggleNeed", value: "calendar" });
    state = reducer(state, { type: "toggleNeed", value: "reminders" });
    expect(state.selectedNeeds).toEqual(["inbox", "mornings", "reminders"]);
  });

  it("counts an open 'Something else' against the cap", () => {
    let state = reducer(initialState, { type: "toggleNeed", value: "inbox" });
    state = reducer(state, { type: "toggleNeed", value: "mornings" });
    state = reducer(state, { type: "toggleOtherNeed" });
    expect(state.otherNeedOpen).toBe(true);

    // Cap spent: neither another chip nor anything else may be picked.
    state = reducer(state, { type: "toggleNeed", value: "calendar" });
    expect(state.selectedNeeds).toEqual(["inbox", "mornings"]);

    // Closing the field frees the pick and forgets the words with it.
    state = reducer(state, { type: "setOtherNeed", value: "invoices" });
    state = reducer(state, { type: "toggleOtherNeed" });
    expect(state).toMatchObject({ otherNeedOpen: false, otherNeed: "" });
    state = reducer(state, { type: "toggleNeed", value: "calendar" });
    expect(state.selectedNeeds).toEqual(["inbox", "mornings", "calendar"]);
  });
});
