/**
 * `integrationSelect` stage. Asks the user to pick 3+ integrations they use
 * most so onboarding workflows can be anchored to real tools. Blocks
 * submission until at least 3 are selected.
 */

"use client";

import * as m from "motion/react-m";
import { type Dispatch, useCallback, useMemo } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import IntegrationChipsSelector from "@/features/workflows/components/workflow-modal/IntegrationChipsSelector";
import { FIELD_NAMES } from "../../constants";
import { BOT_BUBBLE_DEFAULTS } from "../../constants/bubbleDefaults";
import { MOTION_FADE_UP } from "../../constants/motion";
import type { Action, OnboardingState } from "../../state/types";
import { getOnboardingIntegrationPriority } from "../../utils/integrationPriority";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingCTAButton } from "../OnboardingCTAButton";

const MIN_SELECTIONS = 3;

interface IntegrationSelectProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function IntegrationSelect({ state, dispatch }: IntegrationSelectProps) {
  const priorityNames = useMemo(
    () =>
      getOnboardingIntegrationPriority(state.responses[FIELD_NAMES.PROFESSION]),
    [state.responses],
  );

  return (
    <m.div className="mt-4 flex w-full flex-col gap-4" {...MOTION_FADE_UP}>
      <ChatBubbleBot
        {...BOT_BUBBLE_DEFAULTS}
        text="Which apps do you use most? Pick at least 3 so I can build your first workflows around them. You're not connecting anything yet, that happens later. This just helps me learn what you actually use."
      />
      <div className="ml-10.75">
        <IntegrationChipsSelector
          source="catalog"
          variant="pills"
          priorityNames={priorityNames}
          selectedSlugs={state.selectedIntegrations}
          onChange={(slugs) =>
            dispatch({ type: "integrationSelectUpdate", integrations: slugs })
          }
        />
      </div>
    </m.div>
  );
}

export function IntegrationSelectComposer({
  state,
  dispatch,
}: IntegrationSelectProps) {
  const remaining = MIN_SELECTIONS - state.selectedIntegrations.length;
  const canContinue = state.selectedIntegrations.length >= MIN_SELECTIONS;

  const handleContinue = useCallback(() => {
    dispatch({ type: "integrationSelectConfirm" });
  }, [dispatch]);

  if (state.integrationSelectDone) return null;

  return (
    <ComposerCTA>
      <div className="flex flex-col items-center gap-2">
        <OnboardingCTAButton onClick={handleContinue} disabled={!canContinue}>
          Continue
        </OnboardingCTAButton>
        {/* Reserve the line so the hint appearing/clearing never moves the CTA. */}
        <p className="h-4 text-xs text-zinc-500">
          {remaining > 0 ? `Select ${remaining} more to continue` : ""}
        </p>
      </div>
    </ComposerCTA>
  );
}
