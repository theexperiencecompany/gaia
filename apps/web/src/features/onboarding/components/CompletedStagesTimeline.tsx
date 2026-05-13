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

import { useMemo } from "react";
import { FIELD_NAMES } from "../constants";
import type { UseOnboardingChatReturn } from "../hooks/useOnboardingChat";
import type { OnboardingState } from "../state/types";
import { CompletedStageAccordion } from "./CompletedStageAccordion";
import { OnboardingTodoCards } from "./OnboardingTodoCards";
import { WritingStyleRevealCard } from "./reveal/WritingStyleRevealCard";
import { OnboardingChatStream } from "./stages/Chat";

interface CompletedStagesTimelineProps {
  state: OnboardingState;
  chat: UseOnboardingChatReturn;
}

export function CompletedStagesTimeline({
  state,
  chat,
}: CompletedStagesTimelineProps) {
  const writingStyle = state.server?.writing_style;
  const todos = state.server?.onboarding_todos ?? [];
  const workflows = state.server?.suggested_workflows ?? [];

  const showWriting = state.ackedWritingStyle && !!writingStyle?.style_summary;
  const showTodos = state.ackedTodos && todos.length > 0;
  const showWorkflows = state.workflowsConfirmed && workflows.length > 0;
  const showPlatforms = state.platformsConfirmed;

  // OnboardingTodoCards types `source_email` as an object (not nullable). The
  // backend payload returns nullable, so normalise here before handing the list
  // off so we don't widen the card component's contract.
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
            />
            {state.todoExecutionStarted && (
              <OnboardingChatStream
                chat={chat}
                todoOverride={state.todoExecutionTodo}
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
          <ul className="space-y-3">
            {workflows.map((wf, idx) => (
              <li key={wf.id ?? `${wf.title}-${idx}`} className="text-sm">
                <div className="font-medium text-zinc-200">{wf.title}</div>
                {wf.description && (
                  <div className="mt-0.5 text-xs text-zinc-400">
                    {wf.description}
                  </div>
                )}
              </li>
            ))}
          </ul>
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
          <p className="text-sm text-zinc-300">
            {state.connectedPlatform
              ? `You'll receive briefings and urgent notifications on ${state.connectedPlatform}.`
              : "You can connect Telegram, WhatsApp, or Discord later from Settings."}
          </p>
        </CompletedStageAccordion>
      )}
    </div>
  );
}
