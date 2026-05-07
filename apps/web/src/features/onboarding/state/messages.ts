/**
 * Builds the chat-style transcript shown above the composer during the Q&A
 * and processing stages. Pure; derives entirely from `responses` and
 * `questionIndex` so it can be memoised cheaply.
 */

import { FIELD_NAMES, professionOptions, questions } from "../constants";
import {
  FOCUS_QUESTION,
  PROCESSING_MSG_FOCUS,
  PROCESSING_MSG_GMAIL,
  PROCESSING_MSG_NO_GMAIL,
} from "../constants/messages";
import type { Message } from "../types";
import type { OnboardingState } from "./types";

/**
 * Derive the chat-style transcript shown above the input from `responses`
 * + `questionIndex`. Pure function, no side effects.
 *
 * The bot's first follow-up message uses the user's first name as a greeting
 * — that's the only dynamic part. Everything else is a fixed string keyed off
 * the field name.
 */
export function getMessages(state: OnboardingState): Message[] {
  const messages: Message[] = [];
  const { responses, questionIndex } = state;

  for (let i = 0; i < Math.min(questionIndex + 1, questions.length); i++) {
    const q = questions[i];

    let botContent = q.question;
    if (i === 1 && responses[FIELD_NAMES.NAME]) {
      const firstName = responses[FIELD_NAMES.NAME].split(" ")[0];
      botContent = `Nice to meet you, ${firstName}!<NEW_MESSAGE_BREAK>${q.question}`;
    }

    messages.push({
      id: q.id,
      type: "bot",
      content: botContent,
    });

    const answer = responses[q.fieldName];
    if (answer != null) {
      messages.push({
        id: `user-${q.id}`,
        type: "user",
        content: displayValue(q.fieldName, answer),
        questionFieldName: q.fieldName,
      });
    }
  }

  // Past last question — show focus prompt or processing message
  if (questionIndex >= questions.length) {
    const gmail = responses[FIELD_NAMES.GMAIL];
    const focus = responses[FIELD_NAMES.FOCUS];

    if (gmail === "skipped" && focus == null) {
      messages.push({
        id: "focus-q",
        type: "bot",
        content: FOCUS_QUESTION,
      });
    } else if (focus != null) {
      messages.push({
        id: `user-focus`,
        type: "user",
        content: focus,
        questionFieldName: FIELD_NAMES.FOCUS,
      });
      messages.push({
        id: "processing",
        type: "bot",
        content: PROCESSING_MSG_FOCUS,
      });
    } else {
      messages.push({
        id: "processing",
        type: "bot",
        content:
          gmail === "connected"
            ? PROCESSING_MSG_GMAIL
            : PROCESSING_MSG_NO_GMAIL,
      });
    }
  }

  return messages;
}

function displayValue(fieldName: string, value: string): string {
  if (fieldName === FIELD_NAMES.GMAIL) {
    return value === "connected" ? "Connected" : "Continue without Gmail";
  }
  if (fieldName === FIELD_NAMES.PROFESSION) {
    return professionOptions.find((p) => p.value === value)?.label ?? value;
  }
  return value;
}
