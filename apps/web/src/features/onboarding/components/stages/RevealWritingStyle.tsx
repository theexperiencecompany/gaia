/**
 * `revealWriting` stage. Before the user clicks "Looks good", renders the
 * full editable writing-style card inside an intro bubble. After ack, the
 * card collapses into a single confirmed row that can be re-expanded via
 * an accordion. The waiting block ("Looking for things I can help with…")
 * lives below the collapsed row while the rest of the pipeline finishes.
 */

"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Spinner } from "@heroui/spinner";
import { CheckmarkCircle02Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { type Dispatch, useState } from "react";
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

  return (
    <div className="mt-3 space-y-4">
      {state.ackedWritingStyle ? (
        <CollapsedWritingStyle>
          <WritingStyleRevealCard
            style_summary={writingStyle.style_summary}
            example={writingStyle.example ?? null}
            profession={profession}
            embedded
          />
        </CollapsedWritingStyle>
      ) : (
        <RevealIntroBubble text={REVEAL_WRITING_STYLE_INTRO}>
          <WritingStyleRevealCard
            style_summary={writingStyle.style_summary}
            example={writingStyle.example ?? null}
            profession={profession}
          />
        </RevealIntroBubble>
      )}

      <AnimatePresence>
        {state.ackedWritingStyle && (
          <m.div
            key="waiting"
            className="space-y-3"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: EASE_OUT_QUART, delay: 0.1 }}
          >
            <ChatBubbleBot
              {...BOT_BUBBLE_DEFAULTS}
              text="Looking for things I can help with..."
            >
              <div className="mt-2 ml-10.75 flex items-center gap-2">
                <Spinner size="sm" color="default" />
                <span className="text-sm text-zinc-300">
                  {getCurrentProgress(state) ?? "Almost ready"}
                </span>
              </div>
            </ChatBubbleBot>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}

interface CollapsedWritingStyleProps {
  children: React.ReactNode;
}

function CollapsedWritingStyle({ children }: CollapsedWritingStyleProps) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <m.div
      className={`ml-10.75 rounded-2xl bg-zinc-800/40 p-1 backdrop-blur-xl transition-[width,max-width] duration-300 ${
        isOpen ? "w-full" : "w-96"
      }`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: EASE_OUT_QUART }}
    >
      <Accordion
        variant="light"
        className="px-0"
        onSelectionChange={(keys) => {
          const set = keys as Set<string | number>;
          setIsOpen(set.size > 0);
        }}
        itemClasses={{
          base: "px-0",
          trigger: "px-3 py-2 rounded-2xl data-[hover=true]:bg-zinc-700/40",
          titleWrapper: "py-0",
          content: "px-3 pt-2 pb-3",
        }}
      >
        <AccordionItem
          key="writing-style"
          aria-label="Writing style"
          title={
            <div className="flex items-center gap-2">
              <CheckmarkCircle02Icon className="size-4 text-emerald-500" />
              <span className="text-sm font-medium text-zinc-200">
                Writing style saved
              </span>
            </div>
          }
        >
          {children}
        </AccordionItem>
      </Accordion>
    </m.div>
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
