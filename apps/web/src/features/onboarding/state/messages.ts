/**
 * Builds the chat-style transcript shown above the composer. Pure; derives
 * entirely from the answered questions so it can be memoised cheaply.
 */

import { NEW_MESSAGE_BREAK_TOKEN } from "@shared/utils";

import {
  FIELD_NAMES,
  needLabel,
  type OnboardingNeed,
  professionOptions,
  questions,
} from "../constants";
import type { Message } from "../types";

/**
 * The exact slice of onboarding state the transcript derives from, so callers
 * can memoise on just these fields instead of the whole state object.
 */
export interface TranscriptInputs {
  responses: Record<string, string>;
  questionIndex: number;
  selectedNeeds: OnboardingNeed[];
  otherNeed: string;
  /** Given name of the signed-in user, if their account has one. */
  firstName?: string;
}

function answerFor(fieldName: string, state: TranscriptInputs): string | null {
  if (fieldName === FIELD_NAMES.NEEDS) {
    if (state.questionIndex < questions.length) return null;
    const labels = state.selectedNeeds
      .map((need) => needLabel(need))
      .filter((label): label is string => !!label);
    const other = state.otherNeed.trim();
    if (other) labels.push(other);
    return labels.length > 0 ? labels.join(", ") : null;
  }
  const raw = state.responses[fieldName];
  if (raw == null) return null;
  if (fieldName === FIELD_NAMES.PROFESSION) {
    return professionOptions.find((p) => p.value === raw)?.label ?? raw;
  }
  return raw;
}

export function getMessages(state: TranscriptInputs): Message[] {
  const messages: Message[] = [];
  const upTo = Math.min(state.questionIndex + 1, questions.length);

  for (let i = 0; i < upTo; i++) {
    const q = questions[i];
    messages.push({
      id: q.id,
      type: "bot",
      content: q
        .lines(state.responses, { firstName: state.firstName })
        .join(NEW_MESSAGE_BREAK_TOKEN),
    });

    const answer = answerFor(q.fieldName, state);
    if (answer != null) {
      messages.push({
        id: `user-${q.id}`,
        type: "user",
        content: answer,
        questionFieldName: q.fieldName,
      });
    }
  }

  return messages;
}
