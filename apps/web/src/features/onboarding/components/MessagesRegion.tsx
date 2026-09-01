/**
 * Renders the Q&A transcript at the top of the page. Mounted once at the
 * page level so the message list isn't remounted on every stage transition.
 */

"use client";

import { memo, useMemo } from "react";
import { getMessages } from "../state/messages";
import type { OnboardingState } from "../state/types";
import { OnboardingMessages } from "./OnboardingMessages";

interface MessagesRegionProps {
  state: OnboardingState;
}

function MessagesRegionImpl({ state }: MessagesRegionProps) {
  // Narrowed to exactly the fields the transcript derives from so the memo
  // skips recompute on unrelated updates (e.g. typing a draft).
  const { responses, questionIndex, selectedNeeds } = state;
  const messages = useMemo(
    () => getMessages({ responses, questionIndex, selectedNeeds }),
    [responses, questionIndex, selectedNeeds],
  );

  return <OnboardingMessages messages={messages} />;
}

export const MessagesRegion = memo(MessagesRegionImpl);
