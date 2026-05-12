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

import { Mail01Icon } from "@icons";
import { FIELD_NAMES } from "../constants";
import type { UseOnboardingChatReturn } from "../hooks/useOnboardingChat";
import type { OnboardingState } from "../state/types";
import { CompletedStageAccordion } from "./CompletedStageAccordion";
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

  if (!showWriting && !showTodos && !showWorkflows && !showPlatforms) {
    return null;
  }

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
            state.todoExecutionStarted && state.todoExecutionTodo
              ? `Ran "${state.todoExecutionTodo.title}"`
              : `Saved ${todos.length} ${todos.length === 1 ? "todo" : "todos"} for later`
          }
        >
          {state.todoExecutionStarted ? (
            <div className="space-y-4">
              <OnboardingChatStream
                chat={chat}
                todoOverride={state.todoExecutionTodo}
              />
            </div>
          ) : (
            <ul className="space-y-2">
              {todos.map((todo) => (
                <li
                  key={todo.id}
                  className="flex items-start gap-2 text-sm text-zinc-300"
                >
                  <span className="mt-1.5 size-1 shrink-0 rounded-full bg-zinc-500" />
                  <div className="min-w-0 flex-1">
                    <div className="text-zinc-200">{todo.title}</div>
                    {todo.source_email && (
                      <div className="mt-1 flex items-center gap-1.5 text-xs text-zinc-500">
                        <Mail01Icon className="size-3 shrink-0" />
                        <span className="truncate">
                          {todo.source_email.sender}
                        </span>
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
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
