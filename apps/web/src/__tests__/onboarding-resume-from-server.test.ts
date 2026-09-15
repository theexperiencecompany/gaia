// @vitest-environment jsdom
/**
 * Signing in on a second device must not re-ask Q1 and Q2.
 *
 * The wizard's draft lives in localStorage only, so a phone after a laptop —
 * or the same browser with its storage cleared — found no cache and started
 * at question one, even though the answers were already on the account
 * (`PATCH /onboarding/preferences` writes them the moment Q2 is confirmed).
 * Answering again overwrote the stored profession and needs that the platform
 * opener and the agent's context are composed from.
 */
import { renderHook } from "@testing-library/react";
import { useReducer } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import type { OnboardingData } from "@/features/auth/api/authApi";
import { FIELD_NAMES, questions } from "@/features/onboarding/constants";
import { useOnboardingPersistence } from "@/features/onboarding/effects/useOnboardingPersistence";
import { draftFromServerPreferences } from "@/features/onboarding/state/derive";
import { initialState } from "@/features/onboarding/state/initial";
import { savePersisted } from "@/features/onboarding/state/persist";
import { reducer } from "@/features/onboarding/state/reducer";

const USER = "user_alice";

const answeredOnServer: OnboardingData = {
  completed: false,
  preferences: {
    profession: "founder",
    needs: ["inbox", "reminders"],
  },
};

function renderWizard(onboarding: OnboardingData | undefined) {
  return renderHook(() => {
    const [state, dispatch] = useReducer(reducer, initialState);
    useOnboardingPersistence(
      USER,
      draftFromServerPreferences(onboarding),
      state,
      dispatch,
    );
    return state;
  });
}

describe("a device with no draft resumes from the account's answers", () => {
  beforeEach(() => localStorage.clear());

  it("opens past the questions when the server holds Q1 and Q2", () => {
    const { result } = renderWizard(answeredOnServer);

    expect(result.current.questionIndex).toBe(questions.length);
    expect(result.current.responses[FIELD_NAMES.PROFESSION]).toBe("founder");
    expect(result.current.selectedNeeds).toEqual(["inbox", "reminders"]);
    expect(result.current.preferencesPersisted).toBe(true);
  });

  it("still starts at question one for an account that has answered nothing", () => {
    const { result } = renderWizard({ completed: false, preferences: {} });

    expect(result.current.questionIndex).toBe(0);
  });

  it("keeps this device's own progress ahead of the server's copy", () => {
    savePersisted(USER, {
      ...initialState,
      questionIndex: 1,
      responses: { [FIELD_NAMES.PROFESSION]: "designer" },
    });

    const { result } = renderWizard(answeredOnServer);

    expect(result.current.questionIndex).toBe(1);
    expect(result.current.responses[FIELD_NAMES.PROFESSION]).toBe("designer");
  });

  it("drops a need the API no longer accepts", () => {
    const draft = draftFromServerPreferences({
      completed: false,
      preferences: { profession: "founder", needs: ["inbox", "astrology"] },
    });

    expect(draft?.selectedNeeds).toEqual(["inbox"]);
  });

  it("reopens the 'Something else' field the answers were typed into", () => {
    const draft = draftFromServerPreferences({
      completed: false,
      preferences: { profession: "founder", other_need: "chasing invoices" },
    });

    expect(draft?.otherNeed).toBe("chasing invoices");
    expect(draft?.otherNeedOpen).toBe(true);
  });
});
