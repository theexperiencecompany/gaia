/**
 * Builds the chat-style transcript shown above the composer during the Q&A
 * and processing stages. Pure; derives entirely from `responses` and
 * `questionIndex` so it can be memoised cheaply.
 */

import { FIELD_NAMES, professionOptions, questions } from "../constants";
import {
  CLARIFY_INTRO,
  CLARIFY_PROCESSING_MSG,
  CLARIFY_SKIP_REPLY,
} from "../constants/clarify";
import {
  FOCUS_QUESTION,
  PROCESSING_MSG_FOCUS,
  PROCESSING_MSG_GMAIL,
  PROCESSING_MSG_NO_GMAIL,
} from "../constants/messages";
import type { ClarifyAnswer, ClarifyQuestion, Message } from "../types";

/**
 * The exact slice of onboarding state the transcript derives from, so callers
 * can memoise on just these fields instead of the whole state object.
 */
export interface TranscriptInputs {
  responses: Record<string, string>;
  questionIndex: number;
  clarifyQuestions: ClarifyQuestion[] | null;
  clarifyAnswers: Record<string, ClarifyAnswer>;
  clarifySubmitted: boolean;
}

function appendClarifyTranscript(
  messages: Message[],
  state: TranscriptInputs,
): void {
  if (!state.clarifyQuestions) return;
  messages.push({
    id: "clarify-intro",
    type: "bot",
    content: CLARIFY_INTRO,
  });
  for (const q of state.clarifyQuestions) {
    const answer = state.clarifyAnswers[q.id];
    if (!answer) continue;
    messages.push({
      id: `clarify-q-${q.id}`,
      type: "bot",
      content: q.question,
    });
    const userContent =
      answer.kind === "skip" ? CLARIFY_SKIP_REPLY : (answer.value ?? "");
    messages.push({
      id: `clarify-a-${q.id}`,
      type: "user",
      content: userContent,
    });
  }
}

// The bot question + user answer pairs for every question asked so far.
function appendQuestionTranscript(
  messages: Message[],
  state: TranscriptInputs,
): void {
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
}

// The focus question, its answer, optional clarify transcript, and the closing
// processing message — the transcript shown once all questions are answered.
function appendFinalStage(messages: Message[], state: TranscriptInputs): void {
  const { responses } = state;
  const gmail = responses[FIELD_NAMES.GMAIL];
  const focus = responses[FIELD_NAMES.FOCUS];

  if (gmail === "skipped" && focus == null) {
    messages.push({
      id: "focus-q",
      type: "bot",
      content: FOCUS_QUESTION,
    });
    return;
  }

  if (focus == null) {
    messages.push({
      id: "processing",
      type: "bot",
      content:
        gmail === "connected" ? PROCESSING_MSG_GMAIL : PROCESSING_MSG_NO_GMAIL,
    });
    return;
  }

  const isNoGmail = gmail === "skipped";
  if (isNoGmail) {
    messages.push({
      id: "focus-q",
      type: "bot",
      content: FOCUS_QUESTION,
    });
  }
  messages.push({
    id: `user-focus`,
    type: "user",
    content: focus,
    questionFieldName: FIELD_NAMES.FOCUS,
  });

  if (isNoGmail) {
    appendClarifyTranscript(messages, state);
  }

  const showProcessing =
    !isNoGmail || !state.clarifyQuestions || state.clarifySubmitted;
  if (showProcessing) {
    messages.push({
      id: "processing",
      type: "bot",
      content:
        isNoGmail && state.clarifySubmitted
          ? CLARIFY_PROCESSING_MSG
          : PROCESSING_MSG_FOCUS,
    });
  }
}

export function getMessages(state: TranscriptInputs): Message[] {
  const messages: Message[] = [];

  appendQuestionTranscript(messages, state);

  if (state.questionIndex >= questions.length) {
    appendFinalStage(messages, state);
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
