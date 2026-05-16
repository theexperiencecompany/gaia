"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Radio, RadioGroup } from "@heroui/radio";
import { Skeleton } from "@heroui/skeleton";
import { Tab, Tabs } from "@heroui/tabs";
import { CheckmarkCircle02Icon, CircleArrowRight02Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import type { Dispatch } from "react";
import { useCallback, useMemo } from "react";
import {
  CLARIFY_OTHER_LABEL,
  CLARIFY_SKIP_LABEL,
} from "../../constants/clarify";
import { EASE_OUT_QUART } from "../../constants/motion";
import type { Action, OnboardingState } from "../../state/types";
import {
  CLARIFY_RADIO_BASE_CLASS,
  CLARIFY_RADIO_LABEL_CLASS,
  CLARIFY_RADIO_LABEL_MUTED_CLASS,
  countAnsweredClarify,
  isQuestionAnswered,
  OPTION_VALUE_PREFIX,
  OTHER_VALUE,
  radioValueFor,
  SKIP_VALUE,
} from "../../utils/clarifyHelpers";

interface ClarifyProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
}

export function ClarifyComposer({ state, dispatch }: ClarifyProps) {
  const questions = state.clarifyQuestions ?? [];
  const activeId = state.clarifyActiveTab ?? questions[0]?.id ?? "";
  const activeQuestion = useMemo(
    () => questions.find((q) => q.id === activeId) ?? questions[0],
    [questions, activeId],
  );

  const answeredCount = countAnsweredClarify(state);
  const allAnswered =
    questions.length > 0 && answeredCount === questions.length;

  const advanceToNextUnanswered = useCallback(
    (justAnsweredId: string) => {
      const currentIdx = questions.findIndex((q) => q.id === justAnsweredId);
      if (currentIdx < 0) return;
      for (let i = 1; i <= questions.length; i++) {
        const next = questions[(currentIdx + i) % questions.length];
        if (!next || next.id === justAnsweredId) continue;
        const answered = isQuestionAnswered(
          state.clarifyAnswers[next.id],
          state.clarifyCustomDrafts[next.id],
        );
        if (!answered) {
          dispatch({ type: "clarifyTab", questionId: next.id });
          return;
        }
      }
    },
    [questions, state.clarifyAnswers, state.clarifyCustomDrafts, dispatch],
  );

  const handleRadioChange = useCallback(
    (value: string) => {
      if (!activeQuestion) return;
      if (value === SKIP_VALUE) {
        dispatch({ type: "clarifySkip", questionId: activeQuestion.id });
        advanceToNextUnanswered(activeQuestion.id);
        return;
      }
      if (value === OTHER_VALUE) {
        dispatch({ type: "clarifyOtherSelect", questionId: activeQuestion.id });
        return;
      }
      if (value.startsWith(OPTION_VALUE_PREFIX)) {
        const idx = Number(value.slice(OPTION_VALUE_PREFIX.length));
        const option = activeQuestion.options[idx];
        if (option) {
          dispatch({
            type: "clarifySelectOption",
            questionId: activeQuestion.id,
            value: option,
          });
          advanceToNextUnanswered(activeQuestion.id);
        }
      }
    },
    [activeQuestion, dispatch, advanceToNextUnanswered],
  );

  const handleCustomChange = useCallback(
    (value: string) => {
      if (!activeQuestion) return;
      dispatch({
        type: "clarifyCustomDraft",
        questionId: activeQuestion.id,
        value,
      });
    },
    [activeQuestion, dispatch],
  );

  const handleCustomCommit = useCallback(() => {
    if (!activeQuestion) return;
    const draft = state.clarifyCustomDrafts[activeQuestion.id]?.trim();
    dispatch({ type: "clarifyCustomCommit", questionId: activeQuestion.id });
    if (draft) advanceToNextUnanswered(activeQuestion.id);
  }, [
    activeQuestion,
    dispatch,
    state.clarifyCustomDrafts,
    advanceToNextUnanswered,
  ]);

  const handleSubmit = useCallback(() => {
    for (const q of questions) {
      if (
        !state.clarifyAnswers[q.id] &&
        state.clarifyCustomDrafts[q.id]?.trim()
      ) {
        dispatch({ type: "clarifyCustomCommit", questionId: q.id });
      }
    }
    dispatch({ type: "clarifySubmit" });
  }, [questions, state.clarifyAnswers, state.clarifyCustomDrafts, dispatch]);

  if (!activeQuestion) {
    return (
      <m.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: EASE_OUT_QUART }}
        className="mx-2 rounded-2xl bg-zinc-800 p-4"
      >
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-1 rounded-full bg-zinc-900 p-1">
            <Skeleton className="h-6 w-9 rounded-full" />
            <Skeleton className="h-6 w-9 rounded-full" />
            <Skeleton className="h-6 w-9 rounded-full" />
          </div>
          <Skeleton className="h-3 w-8 rounded" />
        </div>
        <div className="rounded-2xl bg-zinc-900 p-3">
          <Skeleton className="mb-3 h-4 w-3/4 rounded" />
          <div className="flex flex-col gap-1.5">
            {["opt-a", "opt-b", "opt-c", "other", "skip"].map((key) => (
              <div
                key={key}
                className="flex items-center gap-2 rounded-xl bg-zinc-800/60 p-2"
              >
                <Skeleton className="size-4 shrink-0 rounded-full" />
                <Skeleton className="h-4 w-2/3 rounded" />
              </div>
            ))}
          </div>
        </div>
        <div className="mt-3 flex justify-end">
          <Skeleton className="h-8 w-36 rounded-full" />
        </div>
      </m.div>
    );
  }

  const activeAnswer = state.clarifyAnswers[activeQuestion.id];
  const activeDraft = state.clarifyCustomDrafts[activeQuestion.id] ?? "";
  const otherSelected = !!state.clarifyOtherSelected[activeQuestion.id];
  const selectedValue = radioValueFor(
    activeQuestion,
    activeAnswer,
    otherSelected,
  );
  const isOtherSelected = selectedValue === OTHER_VALUE;

  return (
    <m.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: EASE_OUT_QUART }}
      className="mx-2 rounded-2xl bg-zinc-800 p-4"
    >
      <div className="mb-3 flex items-center justify-between">
        <Tabs
          aria-label="Clarify questions"
          selectedKey={activeId}
          onSelectionChange={(key) =>
            dispatch({ type: "clarifyTab", questionId: String(key) })
          }
          size="sm"
          variant="solid"
          radius="full"
          classNames={{ tabList: "bg-zinc-900" }}
        >
          {questions.map((q, idx) => {
            const answered = isQuestionAnswered(
              state.clarifyAnswers[q.id],
              state.clarifyCustomDrafts[q.id],
            );
            return (
              <Tab
                key={q.id}
                title={
                  <span className="flex items-center gap-1.5">
                    <span>Q{idx + 1}</span>
                    {answered && (
                      <CheckmarkCircle02Icon className="size-4 text-emerald-400" />
                    )}
                  </span>
                }
              />
            );
          })}
        </Tabs>
        <span className="text-xs text-zinc-500">
          {answeredCount} / {questions.length}
        </span>
      </div>

      <AnimatePresence mode="wait" initial={false}>
        <m.div
          key={activeQuestion.id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25, ease: EASE_OUT_QUART }}
          className="rounded-2xl bg-zinc-900 p-3"
        >
          <p className="mb-3 text-sm text-zinc-100">
            {activeQuestion.question}
          </p>

          <RadioGroup
            value={selectedValue ?? ""}
            onValueChange={handleRadioChange}
            classNames={{ wrapper: "gap-1.5" }}
          >
            {activeQuestion.options.map((option, idx) => (
              <Radio
                key={option}
                value={`${OPTION_VALUE_PREFIX}${idx}`}
                classNames={{
                  base: CLARIFY_RADIO_BASE_CLASS,
                  label: CLARIFY_RADIO_LABEL_CLASS,
                }}
              >
                {option}
              </Radio>
            ))}
            <Radio
              value={OTHER_VALUE}
              classNames={{
                base: CLARIFY_RADIO_BASE_CLASS,
                label: CLARIFY_RADIO_LABEL_CLASS,
              }}
            >
              {CLARIFY_OTHER_LABEL}
            </Radio>
            <AnimatePresence initial={false}>
              {isOtherSelected && (
                <m.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.25, ease: EASE_OUT_QUART }}
                  className="overflow-hidden"
                >
                  <Input
                    autoFocus
                    size="sm"
                    value={activeDraft}
                    onValueChange={handleCustomChange}
                    onBlur={handleCustomCommit}
                    placeholder="Type your answer..."
                    classNames={{
                      inputWrapper:
                        "bg-zinc-800 shadow-none data-[hover=true]:bg-zinc-800 group-data-[focus=true]:bg-zinc-800",
                    }}
                  />
                </m.div>
              )}
            </AnimatePresence>
            <Radio
              value={SKIP_VALUE}
              classNames={{
                base: CLARIFY_RADIO_BASE_CLASS,
                label: CLARIFY_RADIO_LABEL_MUTED_CLASS,
              }}
            >
              {CLARIFY_SKIP_LABEL}
            </Radio>
          </RadioGroup>
        </m.div>
      </AnimatePresence>

      <div className="mt-3 flex justify-end">
        <Button
          color="primary"
          radius="full"
          size="sm"
          isDisabled={!allAnswered}
          onPress={handleSubmit}
          endContent={<CircleArrowRight02Icon className="size-4" />}
        >
          Submit & continue
        </Button>
      </div>
    </m.div>
  );
}
