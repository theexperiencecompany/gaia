/**
 * Editable writing-style summary plus a regenerated example email. Saving
 * an edit hits `/onboarding/writing-style` and then re-renders the example
 * via `/regenerate-example`. Auto-regenerates the example on mount when
 * an existing snapshot lacks one (older DB rows).
 */

"use client";

import { Button } from "@heroui/button";
import { Textarea } from "@heroui/input";
import { Skeleton } from "@heroui/skeleton";
import { Spinner } from "@heroui/spinner";
import { AiMail02Icon, Edit02Icon, QuillWrite01Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useState } from "react";
import { apiService } from "@/lib/api/service";
import type {
  WritingStyleExampleBlocks,
  WritingStyleResults,
} from "../../types/websocket";

const MIN_LENGTH = 20;

interface WritingStyleRevealCardProps extends WritingStyleResults {
  profession?: string;
  embedded?: boolean;
}

const hasExampleContent = (blocks: WritingStyleExampleBlocks | null): boolean =>
  Boolean(blocks && blocks.body.some((p) => p.trim()));

export function WritingStyleRevealCard({
  style_summary,
  example,
  profession = "",
  embedded = false,
}: WritingStyleRevealCardProps) {
  const [isEditingSummary, setIsEditingSummary] = useState(false);
  const [summaryValue, setSummaryValue] = useState(style_summary);
  const [currentExample, setCurrentExample] =
    useState<WritingStyleExampleBlocks | null>(example ?? null);
  const [isSaving, setIsSaving] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (!hasExampleContent(currentExample) && !isRegenerating && summaryValue) {
      setIsRegenerating(true);
      apiService
        .post<{ example: WritingStyleExampleBlocks | null }>(
          "/onboarding/writing-style/regenerate-example",
          { edited_summary: summaryValue, profession },
        )
        .then((res) => {
          if (res.example) setCurrentExample(res.example);
        })
        .catch(() => {})
        .finally(() => {
          setIsRegenerating(false);
        });
    }
    // biome-ignore lint/correctness/useExhaustiveDependencies: intentionally runs on mount only
  }, []);

  const isTooShort = summaryValue.trim().length < MIN_LENGTH;
  const showError = touched && isTooShort;

  const handleSave = async () => {
    setTouched(true);
    if (isTooShort || isSaving) return;
    setIsSaving(true);
    setIsEditingSummary(false);
    setTouched(false);
    try {
      await apiService.post("/onboarding/writing-style", {
        edited_summary: summaryValue.trim(),
      });
      setIsRegenerating(true);
      const res = await apiService.post<{
        example: WritingStyleExampleBlocks | null;
      }>("/onboarding/writing-style/regenerate-example", {
        edited_summary: summaryValue.trim(),
        profession,
      });
      if (res.example) {
        setCurrentExample(res.example);
      }
    } catch {
    } finally {
      setIsSaving(false);
      setIsRegenerating(false);
    }
  };

  const handleCancel = () => {
    setIsEditingSummary(false);
    setSummaryValue(style_summary);
    setTouched(false);
  };

  return (
    <m.div
      className={
        embedded
          ? "space-y-2"
          : "ml-10.75 space-y-2 rounded-2xl bg-zinc-800/60 p-3"
      }
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 280, damping: 22 }}
    >
      <div className="rounded-xl bg-zinc-900 p-3">
        <div className="flex items-start justify-between gap-2 mb-1">
          <div className="flex items-center gap-1.5">
            <QuillWrite01Icon className="size-3.5 shrink-0 text-zinc-500" />
            <p className="text-xs font-medium text-zinc-500">
              Your email writing style
            </p>
          </div>
          <Button
            isIconOnly
            size="sm"
            variant="light"
            aria-label="Edit writing style"
            onPress={() => setIsEditingSummary(true)}
            className="shrink-0 -mt-0.5 -mr-1 text-zinc-600 hover:text-zinc-400 min-w-6 w-6 h-6"
            style={{ visibility: isEditingSummary ? "hidden" : "visible" }}
          >
            <Edit02Icon className="size-3.5" />
          </Button>
        </div>

        {isEditingSummary ? (
          <>
            <Textarea
              value={summaryValue}
              onValueChange={(v) => {
                setSummaryValue(v);
                setTouched(true);
              }}
              minRows={3}
              variant="flat"
              isInvalid={showError}
              errorMessage={
                showError ? "Style description is too short." : undefined
              }
              classNames={{
                inputWrapper: "bg-zinc-800 shadow-none",
                input: "text-sm text-zinc-200 leading-relaxed",
              }}
              // biome-ignore lint/a11y/noAutofocus: intentional focus on edit
              autoFocus
            />
            <div className="flex items-center justify-end gap-2 mt-2">
              <Button size="sm" variant="light" onPress={handleCancel}>
                Cancel
              </Button>
              <Button
                size="sm"
                color="primary"
                isDisabled={isSaving}
                onPress={handleSave}
              >
                {isSaving ? <Spinner size="sm" color="current" /> : "Save"}
              </Button>
            </div>
          </>
        ) : (
          <p className="text-sm text-zinc-200 leading-relaxed">
            {summaryValue}
          </p>
        )}
      </div>

      <div className="rounded-xl bg-zinc-900 p-3">
        <div className="flex items-center gap-1.5 mb-2">
          <AiMail02Icon className="size-3.5 shrink-0 text-zinc-500" />
          <p className="text-xs font-medium text-zinc-500">
            Example email in your voice
          </p>
        </div>
        <AnimatePresence mode="wait">
          {isRegenerating || !hasExampleContent(currentExample) ? (
            <m.div
              key="skeleton"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-2"
            >
              <Skeleton className="h-3 w-full rounded-lg" />
              <Skeleton className="h-3 w-5/6 rounded-lg" />
              <Skeleton className="h-3 w-4/5 rounded-lg" />
              <Skeleton className="h-3 w-3/4 rounded-lg" />
            </m.div>
          ) : (
            <m.div
              key="example"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="space-y-3 text-sm text-zinc-200 leading-relaxed"
            >
              {currentExample?.greeting.trim() && (
                <p>{currentExample.greeting}</p>
              )}
              {currentExample?.body
                .filter((p) => p.trim())
                .map((paragraph, idx) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: paragraphs are rendered immutably from a single LLM response
                  <p key={idx}>{paragraph}</p>
                ))}
              {(currentExample?.signoff.trim() ||
                currentExample?.name.trim()) && (
                <div>
                  {currentExample.signoff.trim() && (
                    <p>{currentExample.signoff}</p>
                  )}
                  {currentExample.name.trim() && <p>{currentExample.name}</p>}
                </div>
              )}
            </m.div>
          )}
        </AnimatePresence>
      </div>
    </m.div>
  );
}
