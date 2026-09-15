/**
 * Renders the Q&A transcript at the top of the page. Mounted once at the
 * page level so the message list isn't remounted on every stage transition.
 */

"use client";

import { memo, useMemo } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { firstNameOf } from "@/features/auth/utils/firstName";
import { getMessages } from "../state/messages";
import type { OnboardingState } from "../state/types";
import { OnboardingMessages } from "./OnboardingMessages";

interface MessagesRegionProps {
  state: OnboardingState;
}

function MessagesRegionImpl({ state }: MessagesRegionProps) {
  // Narrowed to exactly the fields the transcript derives from so the memo
  // skips recompute on unrelated updates (e.g. typing a draft).
  const { responses, questionIndex, selectedNeeds, otherNeed } = state;
  const { name, email } = useCurrentUser();
  const firstName = firstNameOf(name, email);
  const messages = useMemo(
    () =>
      getMessages({
        responses,
        questionIndex,
        selectedNeeds,
        otherNeed,
        firstName,
      }),
    [responses, questionIndex, selectedNeeds, otherNeed, firstName],
  );

  return <OnboardingMessages messages={messages} />;
}

export const MessagesRegion = memo(MessagesRegionImpl);
