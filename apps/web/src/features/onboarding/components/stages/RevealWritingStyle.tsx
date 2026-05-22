/**
 * `revealWriting` stage. Renders the full editable writing-style card inside
 * an intro bubble until the user clicks "Looks good". After ack, this stage
 * owns only the "Looking for things I can help with…" holding bubble — the
 * collapsed post-ack card now lives in the persistent `CompletedStagesTimeline`
 * above so every completed stage uses one shared accordion pattern.
 */

"use client";

import { Spinner } from "@heroui/spinner";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import type { Dispatch } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import { FIELD_NAMES } from "../../constants";
import { BOT_BUBBLE_DEFAULTS } from "../../constants/bubbleDefaults";
import { REVEAL_WRITING_STYLE_INTRO } from "../../constants/messages";
import { EASE_OUT_QUART } from "../../constants/motion";
import { getCurrentProgress } from "../../state/derive";
import type { Action, OnboardingState } from "../../state/types";
import { ComposerCTA } from "../ComposerCTA";
import { OnboardingCTAButton } from "../OnboardingCTAButton";
import { RevealIntroBubble } from "../RevealIntroBubble";
import { WritingStyleRevealCard } from "../reveal/WritingStyleRevealCard";

interface RevealWritingStyleProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function RevealWritingStyle({ state }: { state: OnboardingState }) {
  const writingStyle = state.server?.writing_style;
  const profession = state.responses[FIELD_NAMES.PROFESSION] ?? "";

  if (!writingStyle?.style_summary) return null;

  if (state.ackedWritingStyle) {
    return (
      <AnimatePresence>
        <m.div
          key="waiting"
          className="mt-3 space-y-3"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: EASE_OUT_QUART, delay: 0.1 }}
        >
          <ChatBubbleBot
            {...BOT_BUBBLE_DEFAULTS}
            text="Looking for things I can help with..."
          >
            <div className="mt-2 ml-10.75 flex items-center gap-2">
              <Spinner size="sm" color="primary" />
              <span className="text-sm text-zinc-300">
                {getCurrentProgress(state) ?? "Almost ready"}
              </span>
            </div>
          </ChatBubbleBot>
        </m.div>
      </AnimatePresence>
    );
  }

  return (
    <div className="mt-3 space-y-4">
      <RevealIntroBubble text={REVEAL_WRITING_STYLE_INTRO}>
        <WritingStyleRevealCard
          style_summary={writingStyle.style_summary}
          example={writingStyle.example ?? null}
          profession={profession}
        />
      </RevealIntroBubble>
    </div>
  );
}

export function RevealWritingStyleComposer({
  state,
  dispatch,
}: RevealWritingStyleProps) {
  if (state.ackedWritingStyle) return null;
  if (!state.server?.writing_style?.style_summary) return null;

  return (
    <ComposerCTA>
      <OnboardingCTAButton onClick={() => dispatch({ type: "ackWriting" })}>
        Looks good
      </OnboardingCTAButton>
    </ComposerCTA>
  );
}
