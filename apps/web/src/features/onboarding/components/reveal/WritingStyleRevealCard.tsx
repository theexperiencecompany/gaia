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
import { AnimatePresence, m } from "motion/react";
import { useEffect, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { apiService } from "@/lib/api/service";
import type { WritingStyleResults } from "../../types/websocket";

const MIN_LENGTH = 20;

interface WritingStyleRevealCardProps extends WritingStyleResults {
  profession?: string;
}

export function WritingStyleRevealCard({
  style_summary,
  example,
  profession = "",
}: WritingStyleRevealCardProps) {
  const [isEditingSummary, setIsEditingSummary] = useState(false);
  const [summaryValue, setSummaryValue] = useState(style_summary);
  const [currentExample, setCurrentExample] = useState(example ?? "");
  const [isSaving, setIsSaving] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [touched, setTouched] = useState(false);

  // Auto-regenerate example on mount if missing (e.g. old DB records lacking example field)
  useEffect(() => {
    if (!currentExample && !isRegenerating && summaryValue) {
      setIsRegenerating(true);
      apiService
        .post<{ example: string }>(
          "/onboarding/writing-style/regenerate-example",
          { edited_summary: summaryValue, profession },
        )
        .then((res) => {
          if (res.example) setCurrentExample(res.example);
        })
        .catch(() => {
          // silent — non-blocking
        })
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
      const res = await apiService.post<{ example: string }>(
        "/onboarding/writing-style/regenerate-example",
        { edited_summary: summaryValue.trim(), profession },
      );
      if (res.example) {
        setCurrentExample(res.example);
      }
    } catch {
      // silent — non-blocking
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
      className="overflow-hidden rounded-2xl bg-zinc-800/60 p-4 space-y-3 ml-10.75"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 280, damping: 22 }}
    >
      {/* Editable summary */}
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
              <RaisedButton size="sm" disabled={isSaving} onClick={handleSave}>
                {isSaving ? <Spinner size="sm" color="current" /> : "Save"}
              </RaisedButton>
            </div>
          </>
        ) : (
          <p className="text-sm text-zinc-200 leading-relaxed">
            {summaryValue}
          </p>
        )}
      </div>

      {/* Example email */}
      <div className="rounded-xl bg-zinc-900 p-3">
        <div className="flex items-center gap-1.5 mb-2">
          <AiMail02Icon className="size-3.5 shrink-0 text-zinc-500" />
          <p className="text-xs font-medium text-zinc-500">
            Example email in your voice
          </p>
        </div>
        <AnimatePresence mode="wait">
          {isRegenerating || !currentExample ? (
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
            <m.p
              key="example"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="text-sm text-zinc-200 leading-relaxed whitespace-pre-wrap"
            >
              {currentExample}
            </m.p>
          )}
        </AnimatePresence>
      </div>
    </m.div>
  );
}
