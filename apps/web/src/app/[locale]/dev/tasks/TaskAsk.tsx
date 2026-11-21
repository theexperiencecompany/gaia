"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  ArrowUp02Icon,
  BubbleChatIcon,
  CheckmarkCircle02Icon,
  Link01Icon,
} from "@icons";
import { getToolDisplayName } from "@shared/icons";
import { useState } from "react";

import type { Task } from "./taskModel";

/** The answers a task's ask can take, each one a real call: the approval ledger, the task's chat, or the connect flow. */
export type AskAnswer =
  | { kind: "approve" }
  | { kind: "deny" }
  | { kind: "reply"; text: string }
  | { kind: "reconnect" };

const LABEL = {
  approval: { text: "Needs your approval", Icon: CheckmarkCircle02Icon },
  question: { text: "GAIA has a question", Icon: BubbleChatIcon },
  reconnect: { text: "Needs reconnecting", Icon: Link01Icon },
} as const;

/** The thing GAIA wants to send, as the approval card carries it (args_preview). */
function Draft({ draft }: { draft: NonNullable<Task["ask"]>["draft"] }) {
  if (!draft) return null;
  return (
    <div className="space-y-2 rounded-2xl bg-zinc-900 p-3">
      <dl className="space-y-1 text-xs">
        <div className="flex gap-2">
          <dt className="w-12 shrink-0 text-zinc-500">To</dt>
          <dd className="truncate text-zinc-300">{draft.to}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-12 shrink-0 text-zinc-500">Subject</dt>
          <dd className="truncate text-zinc-300">{draft.subject}</dd>
        </div>
      </dl>
      <p className="whitespace-pre-line text-sm leading-6 text-zinc-200">
        {draft.body}
      </p>
    </div>
  );
}

function ReplyBox({ onSend }: { onSend: (text: string) => void }) {
  const [text, setText] = useState("");
  const send = () => {
    if (text.trim()) onSend(text.trim());
  };
  return (
    <Input
      aria-label="Reply to GAIA"
      value={text}
      onValueChange={setText}
      onKeyDown={(event) => event.key === "Enter" && send()}
      placeholder="Reply to GAIA"
      variant="flat"
      classNames={{
        inputWrapper:
          "h-10 rounded-xl bg-zinc-900 pr-1 shadow-none data-[hover=true]:bg-zinc-900 group-data-[focus=true]:bg-zinc-900 group-data-[focus-visible=true]:ring-0 group-data-[focus-visible=true]:ring-offset-0",
        input: "text-sm placeholder:text-zinc-500",
      }}
      endContent={
        <Button
          isIconOnly
          size="sm"
          radius="full"
          color="primary"
          aria-label="Send reply"
          isDisabled={!text.trim()}
          onPress={send}
          className="size-7 min-w-7"
        >
          <ArrowUp02Icon className="size-4 text-black" />
        </Button>
      }
    />
  );
}

/**
 * What GAIA is blocked on, answerable in place. An approval shows what will be
 * sent; a question takes a reply; a lost connection offers to reconnect.
 */
export default function TaskAsk({
  task,
  onAnswer,
}: {
  task: Task;
  onAnswer: (answer: AskAnswer) => void;
}) {
  const ask = task.ask;
  if (!ask) return null;
  const { text, Icon } = LABEL[ask.kind];

  return (
    <section className="space-y-3 rounded-2xl bg-zinc-800 p-4">
      <p className="flex items-center gap-1.5 text-xs font-medium text-amber-400">
        <Icon className="size-3.5" />
        {text}
      </p>
      <p className="text-sm leading-6 text-zinc-100">{ask.prompt}</p>

      {ask.kind === "approval" && (
        <>
          <Draft draft={ask.draft} />
          <div className="flex gap-2">
            <Button
              size="sm"
              color="primary"
              className="font-medium"
              onPress={() => onAnswer({ kind: "approve" })}
            >
              Approve and send
            </Button>
            <Button
              size="sm"
              variant="flat"
              onPress={() => onAnswer({ kind: "deny" })}
            >
              Don't send
            </Button>
          </div>
        </>
      )}

      {ask.kind === "question" && (
        <>
          <ReplyBox
            onSend={(reply) => onAnswer({ kind: "reply", text: reply })}
          />
          {ask.ifNoReply && (
            <p className="text-xs leading-5 text-zinc-500">{ask.ifNoReply}</p>
          )}
        </>
      )}

      {ask.kind === "reconnect" && (
        <Button
          size="sm"
          color="primary"
          className="font-medium"
          startContent={<Link01Icon className="size-4" />}
          onPress={() => onAnswer({ kind: "reconnect" })}
        >
          Reconnect {getToolDisplayName(task.integrations[0] ?? "")}
        </Button>
      )}
    </section>
  );
}
