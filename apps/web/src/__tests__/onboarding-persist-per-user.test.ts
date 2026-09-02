// @vitest-environment jsdom
/**
 * Wizard progress is cached in localStorage so a reload resumes where the user
 * left off. That cache belongs to one account: a second person signing up on
 * the same browser must start at question one, not inherit the previous
 * account's answers and land on the payment stage (D16, found on the live
 * click-through).
 */
import { beforeEach, describe, expect, it } from "vitest";

import { initialState } from "@/features/onboarding/state/initial";
import {
  clearPersisted,
  loadPersisted,
  savePersisted,
} from "@/features/onboarding/state/persist";

const ALICE = "user_alice";
const BOB = "user_bob";

describe("wizard persistence is scoped to the signed-in user", () => {
  beforeEach(() => localStorage.clear());

  it("does not hand one user's progress to another", () => {
    savePersisted(ALICE, {
      ...initialState,
      questionIndex: 2,
      responses: { profession: "founder" },
    });

    expect(loadPersisted(BOB)).toBeNull();
    expect(loadPersisted(ALICE)?.questionIndex).toBe(2);
  });

  it("clears only the restarting user's cache", () => {
    savePersisted(ALICE, { ...initialState, questionIndex: 1 });
    savePersisted(BOB, { ...initialState, questionIndex: 2 });

    clearPersisted(ALICE);

    expect(loadPersisted(ALICE)).toBeNull();
    expect(loadPersisted(BOB)?.questionIndex).toBe(2);
  });
});
