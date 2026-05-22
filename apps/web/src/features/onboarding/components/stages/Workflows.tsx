/**
 * `workflows` stage. Shows the suggested workflows and an "Understood" CTA.
 * Once confirmed, the linear stage cursor advances to `platforms` (handled
 * by the page). This stage is responsible for the workflows display only —
 * platform-connect is its own stage.
 */

"use client";

import { CircleArrowUp02Icon } from "@icons";
import * as m from "motion/react-m";
import type { Dispatch } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import { BOT_BUBBLE_DEFAULTS } from "../../constants/bubbleDefaults";
import {
  WORKFLOWS_INTRO_PRIMARY,
  WORKFLOWS_INTRO_SECONDARY,
} from "../../constants/messages";
import { MOTION_FADE_UP_LARGE } from "../../constants/motion";
import type { Action, OnboardingState } from "../../state/types";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { OnboardingWorkflowCards } from "../OnboardingWorkflowCards";

interface WorkflowsProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function Workflows({ state }: WorkflowsProps) {
  const workflows = state.server?.suggested_workflows ?? [];
  const workflowsConfirmed = state.workflowsConfirmed;

  if (workflows.length === 0) return null;

  return (
    <m.div className="mt-4 space-y-4" {...MOTION_FADE_UP_LARGE}>
      <ChatBubbleBot
        {...BOT_BUBBLE_DEFAULTS}
        text={`${WORKFLOWS_INTRO_PRIMARY}<NEW_MESSAGE_BREAK>${WORKFLOWS_INTRO_SECONDARY}`}
      >
        <div className="mt-3">
          <OnboardingWorkflowCards workflows={workflows} />
        </div>
        {!workflowsConfirmed && (
          <p className="mt-2 ml-10.75 flex items-center gap-1 text-xs text-zinc-300">
            Here's what I set up to get you started
            <CircleArrowUp02Icon width={14} height={14} />
          </p>
        )}
      </ChatBubbleBot>
    </m.div>
  );
}

export function WorkflowsComposer({ dispatch }: WorkflowsProps) {
  return (
    <ComposerCTA>
      <OnboardingCTAButton
        onClick={() => dispatch({ type: "confirmWorkflows" })}
      >
        Understood
      </OnboardingCTAButton>
    </ComposerCTA>
  );
}
