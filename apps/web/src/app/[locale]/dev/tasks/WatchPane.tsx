"use client";

import { InputGroup, Spinner, TextArea } from "@heroui/react";
import { ArrowUp02Icon, BubbleChatIcon, ViewOffIcon } from "@icons";
import { useEffect, useRef, useState } from "react";

import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { toneVariants } from "@/components/shared/tone";
import {
  CHECK_MS,
  EXAMPLE,
  lookDaily,
  readSentence,
  type SentenceRead,
} from "./demoWatches";
import type { TaskWhen } from "./taskModel";
import WatchProposal, { WatchProposalSkeleton } from "./WatchProposal";
import { TextAction } from "./WhenParts";
import { onWatch } from "./watchModel";

type Phase =
  | { kind: "writing" }
  | { kind: "checking" }
  | { kind: "set" }
  | Extract<SentenceRead, { kind: "question" | "failed" }>;

/** The checking state, the proposal and the question all fill this, so nothing moves when one replaces another. */
const RESULT_HEIGHT = "min-h-[19.25rem]";

/**
 * "When something changes": the user says it in a sentence, GAIA reads it once,
 * checks it for real, and shows what it will watch. A missing detail is asked
 * as one question; a source it can't see is never set up.
 */
export default function WatchPane({
  when,
  onChange,
}: {
  when: TaskWhen;
  onChange: (when: TaskWhen) => void;
}) {
  const watch = when.watch;
  const [sentence, setSentence] = useState(watch?.sentence ?? "");
  const [answer, setAnswer] = useState("");
  const [phase, setPhase] = useState<Phase>(
    watch ? { kind: "set" } : { kind: "writing" },
  );
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const field = useRef<HTMLTextAreaElement>(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  const settle = (read: SentenceRead) => {
    if (read.kind === "proposal") {
      onChange(onWatch(read.watch, read.ends));
      setPhase({ kind: "set" });
      // The answer field is gone, so the sentence keeps focus rather than the tabs.
      field.current?.focus();
    } else setPhase(read);
  };

  const check = (withAnswer?: string) => {
    const text = sentence.trim();
    if (!text) return;
    setPhase({ kind: "checking" });
    clearTimeout(timer.current);
    timer.current = setTimeout(
      () => settle(readSentence(text, withAnswer)),
      CHECK_MS,
    );
  };

  const isStale =
    phase.kind === "set" && !!watch && sentence.trim() !== watch.sentence;

  return (
    <div className="space-y-3">
      <TextArea
        ref={field}
        autoFocus={!watch}
        aria-label="What should GAIA watch for?"
        value={sentence}
        onChange={(event) => setSentence(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            check();
          }
        }}
        placeholder={EXAMPLE}
        rows={2}
        className={inputVariants({
          variant: "sunken",
          placeholder: "subtle",
          className: toneVariants({
            tone: "white",
            className: "block w-full resize-none text-sm leading-5",
          }),
        })}
      />

      {phase.kind === "writing" && (
        <div className="flex h-9 items-center justify-between gap-3">
          <p className="px-1 text-xs leading-4 text-zinc-500">
            A price, a new post, a reply.
          </p>
          <GaiaButton
            size="sm"
            variant="default-solid"
            tone="strong"
            isDisabled={!sentence.trim()}
            onPress={() => check()}
            className="h-9 shrink-0"
          >
            Check
          </GaiaButton>
        </div>
      )}

      {phase.kind !== "writing" && (
        <div className={RESULT_HEIGHT}>
          {phase.kind === "checking" && (
            <WatchProposalSkeleton
              footnote={
                <p className="flex items-center gap-2 px-1 pt-1 text-xs leading-5 text-zinc-500">
                  <Spinner size="sm" />
                  Checking it now, before saving
                </p>
              }
            />
          )}

          {phase.kind === "set" && watch && (
            <WatchProposal
              watch={watch}
              ends={when.ends}
              isStale={isStale}
              onChange={(next, ends) =>
                onChange(onWatch({ ...next, sentence: watch.sentence }, ends))
              }
              footnote={
                isStale ? (
                  <TextAction onPress={() => check()}>
                    Check it again
                  </TextAction>
                ) : undefined
              }
            />
          )}

          {phase.kind === "question" && (
            <div className="space-y-3">
              <p className="flex gap-2 px-1 text-sm leading-5 text-zinc-100">
                <BubbleChatIcon className="mt-0.5 size-4 shrink-0 text-zinc-400" />
                {phase.question}
              </p>
              <InputGroup
                className={inputVariants({
                  variant: "sunken",
                  className: "w-full",
                })}
              >
                <InputGroup.Input
                  autoFocus
                  aria-label="Answer"
                  value={answer}
                  onChange={(event) => setAnswer(event.target.value)}
                  onKeyDown={(event) =>
                    event.key === "Enter" && answer.trim() && check(answer)
                  }
                  placeholder="AI 101, Dec 3"
                  className={inputVariants({
                    placeholder: "subtle",
                    className: toneVariants({
                      tone: "white",
                      className: "text-sm",
                    }),
                  })}
                />
                <InputGroup.Suffix>
                  <GaiaButton
                    isIconOnly
                    size="sm"
                    shape="pill"
                    variant="primary"
                    aria-label="Send answer"
                    isDisabled={!answer.trim()}
                    onPress={() => check(answer)}
                    className="size-7 min-w-7"
                  >
                    <ArrowUp02Icon className="size-4 text-black" />
                  </GaiaButton>
                </InputGroup.Suffix>
              </InputGroup>
            </div>
          )}

          {phase.kind === "failed" && (
            <div className="space-y-2">
              <p className="flex gap-2 px-1 text-sm leading-5 text-zinc-100">
                <ViewOffIcon className="mt-0.5 size-4 shrink-0 text-amber-400" />
                {phase.line}
              </p>
              <div className="flex flex-col items-start">
                <TextAction onPress={() => check()}>Try again</TextAction>
                <TextAction onPress={() => settle(lookDaily(sentence.trim()))}>
                  Have GAIA search for it once a day instead
                </TextAction>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
