/**
 * Persistent timeline that records each completed onboarding stage as a
 * `CompletedStageAccordion`. Renders between `MessagesRegion` and the active
 * stage panel; each accordion appears as its stage is acked and stays for
 * the rest of the flow so the user can scroll up and re-open any prior step.
 *
 * Order matches the linear stage queue: writing style → todos → workflows →
 * platforms. The accordions are independent — the active stage is responsible
 * for rendering its own in-progress UI.
 */

"use client";

import { type Dispatch, useMemo } from "react";
import { FIELD_NAMES } from "../constants";
import { useConnectPlatform } from "../hooks/useConnectPlatform";
import type { UseOnboardingChatReturn } from "../hooks/useOnboardingChat";
import type { Action, OnboardingState } from "../state/types";
import { CompletedStageAccordion } from "./CompletedStageAccordion";
import { OnboardingPlatformConnect } from "./OnboardingPlatformConnect";
import { OnboardingTodoCards } from "./OnboardingTodoCards";
import { OnboardingWorkflowCards } from "./OnboardingWorkflowCards";
import { WritingStyleRevealCard } from "./reveal/WritingStyleRevealCard";
import { OnboardingChatStream } from "./stages/ChatStream";

interface CompletedStagesTimelineProps {
  state: OnboardingState;
  dispatch: Dispatch<Action>;
  chat: UseOnboardingChatReturn;
}

export function CompletedStagesTimeline({
  state,
  dispatch,
  chat,
}: CompletedStagesTimelineProps) {
  const { connect, skip } = useConnectPlatform(dispatch);
  const writingStyle = state.server?.writing_style;
  const todos = state.server?.onboarding_todos ?? [];
  const workflows = state.server?.suggested_workflows ?? [];

  const showWriting = state.ackedWritingStyle && !!writingStyle?.style_summary;
  const showTodos = state.ackedTodos && todos.length > 0;
  const showWorkflows = state.workflowsConfirmed && workflows.length > 0;
  const showPlatforms = state.platformsConfirmed;

  const cardTodos = useMemo(
    () =>
      todos.map((t) => ({
        id: t.id,
        title: t.title,
        description: t.description ?? undefined,
        source_email: t.source_email ?? undefined,
      })),
    [todos],
  );

  const executedTodoIds = useMemo(
    () =>
      state.todoExecutionTodo
        ? new Set([state.todoExecutionTodo.id])
        : new Set<string>(),
    [state.todoExecutionTodo],
  );

  if (!showWriting && !showTodos && !showWorkflows && !showPlatforms) {
    return null;
  }

  const executedTitle = state.todoExecutionTodo?.title;

  return (
    <div className="mt-3 space-y-3">
      {showWriting && writingStyle?.style_summary && (
        <CompletedStageAccordion
          itemKey="writing-style"
          title="Writing style saved"
        >
          <WritingStyleRevealCard
            style_summary={writingStyle.style_summary}
            example={writingStyle.example ?? null}
            profession={state.responses[FIELD_NAMES.PROFESSION] ?? ""}
            embedded
          />
        </CompletedStageAccordion>
      )}

      {showTodos && (
        <CompletedStageAccordion
          itemKey="todos"
          title={
            state.todoExecutionStarted && executedTitle
              ? `Ran "${executedTitle}"`
              : `Saved ${todos.length} ${todos.length === 1 ? "todo" : "todos"} for later`
          }
        >
          <div className="space-y-4">
            <OnboardingTodoCards
              todos={cardTodos}
              onExecuteTodo={() => {}}
              isExecuting={false}
              executingTodoId={null}
              completedTodoIds={executedTodoIds}
              readOnly
              embedded
            />
            {state.todoExecutionStarted && (
              <OnboardingChatStream
                chat={chat}
                hideRunNowUserMessage
                hideBotAvatar
              />
            )}
          </div>
        </CompletedStageAccordion>
      )}

      {showWorkflows && (
        <CompletedStageAccordion
          itemKey="workflows"
          title={`${workflows.length} ${workflows.length === 1 ? "workflow" : "workflows"} added`}
        >
          <OnboardingWorkflowCards workflows={workflows} embedded />
        </CompletedStageAccordion>
      )}

      {showPlatforms && (
        <CompletedStageAccordion
          itemKey="platforms"
          title={
            state.connectedPlatform
              ? `Connected ${state.connectedPlatform}`
              : "Skipped social connections"
          }
        >
          <OnboardingPlatformConnect
            onConnect={connect}
            onSkip={skip}
            onHoverPlatform={() => {}}
            hideSkip
            embedded
          />
        </CompletedStageAccordion>
      )}
    </div>
  );
}
