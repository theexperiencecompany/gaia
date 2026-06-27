/**
 * `integrationSelect` stage. Asks the user to pick 3+ integrations they use
 * most so onboarding workflows can be anchored to real tools. Blocks
 * submission until at least 3 are selected.
 */

"use client";

import * as m from "motion/react-m";
import { type Dispatch, useCallback } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import IntegrationChipsSelector from "@/features/workflows/components/workflow-modal/IntegrationChipsSelector";
import { BOT_BUBBLE_DEFAULTS } from "../../constants/bubbleDefaults";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { Action, OnboardingState } from "../../state/types";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingCTAButton } from "../OnboardingCTAButton";

const MIN_SELECTIONS = 3;

interface IntegrationSelectProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function IntegrationSelect({ state, dispatch }: IntegrationSelectProps) {
  const remaining = MIN_SELECTIONS - state.selectedIntegrations.length;

  return (
    <m.div
      className="mt-4 flex flex-col items-center gap-4"
      {...MOTION_FADE_UP}
    >
      <div className="w-full max-w-xl">
        <ChatBubbleBot
          {...BOT_BUBBLE_DEFAULTS}
          text="Which apps do you use most? Pick at least 3 and I'll build your first workflows around the tools you already live in."
        />
      </div>
      <div className="w-full max-w-xl rounded-2xl bg-zinc-800 p-5">
        <IntegrationChipsSelector
          source="catalog"
          selectedSlugs={state.selectedIntegrations}
          onChange={(slugs) =>
            dispatch({ type: "integrationSelectUpdate", integrations: slugs })
          }
          autocompleteClassName="w-full"
        />
        {state.selectedIntegrations.length > 0 && remaining > 0 && (
          <p className="mt-3 text-center text-xs text-zinc-500">
            Select {remaining} more to continue
          </p>
        )}
      </div>
    </m.div>
  );
}

export function IntegrationSelectComposer({
  state,
  dispatch,
}: IntegrationSelectProps) {
  const canContinue = state.selectedIntegrations.length >= MIN_SELECTIONS;

  const handleContinue = useCallback(() => {
    dispatch({ type: "integrationSelectConfirm" });
  }, [dispatch]);

  const handleSkip = useCallback(() => {
    dispatch({ type: "integrationSelectConfirm" });
  }, [dispatch]);

  if (state.integrationSelectDone) return null;

  return (
    <ComposerCTA>
      <div className="flex gap-3">
        <OnboardingCTAButton onClick={handleContinue} disabled={!canContinue}>
          Continue
        </OnboardingCTAButton>
        <OnboardingCTAButton onClick={handleSkip} hideEndIcon>
          I'll choose later
        </OnboardingCTAButton>
      </div>
    </ComposerCTA>
  );
}
