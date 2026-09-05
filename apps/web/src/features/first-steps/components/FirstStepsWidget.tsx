"use client";

import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import { Progress } from "@heroui/progress";
import {
  Cancel01Icon,
  CheckmarkCircle02Icon,
  CircleIcon,
  MinusSignIcon,
} from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import NextLink from "next/link";
import { useFirstStepsWidget } from "@/features/first-steps/hooks/useFirstStepsWidget";

// One persistent shell morphs between pill and panel — size and radius animate
// continuously; only the content crossfades. No overshoot: an overshooting
// spring visibly distorts the border radius mid-morph.
const morphSpring = {
  type: "spring",
  stiffness: 600,
  damping: 48,
} as const;

const contentFade = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.12 },
} as const;

// Pill is 40px tall, so 20px reads as fully rounded while keeping the
// radius morph numeric (20 -> 16) instead of jumping from 9999.
const PILL_RADIUS = 20;
const PANEL_RADIUS = 16;

export function FirstStepsWidget() {
  const {
    shouldRender,
    expanded,
    setExpanded,
    visibleSteps,
    completedAt,
    completedCount,
    totalCount,
    hideStep,
    dismiss,
  } = useFirstStepsWidget();

  if (!shouldRender) return null;

  return (
    <div className="fixed right-4 bottom-4 z-40">
      <m.div
        layout
        transition={morphSpring}
        initial={false}
        animate={{ borderRadius: expanded ? PANEL_RADIUS : PILL_RADIUS }}
        className="overflow-hidden bg-zinc-800 shadow-lg"
      >
        <AnimatePresence initial={false} mode="popLayout">
          {!expanded ? (
            <m.button
              key="pill"
              layout
              {...contentFade}
              type="button"
              onClick={() => setExpanded(true)}
              className="flex h-10 items-center gap-2 px-4 transition-colors hover:bg-zinc-700"
            >
              <Progress
                aria-label="Activation progress"
                value={(completedCount / totalCount) * 100}
                size="sm"
                color="success"
                className="w-16"
              />
              <span className="text-xs font-medium text-zinc-200">
                {completedCount}/{totalCount}
              </span>
            </m.button>
          ) : (
            <m.div key="panel" layout {...contentFade} className="w-80 p-4">
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold text-zinc-100">
                    Get started
                  </p>
                  <p className="text-xs text-zinc-500">
                    {completedCount}/{totalCount} complete
                  </p>
                </div>
                <div className="flex items-center">
                  <Button
                    isIconOnly
                    size="sm"
                    variant="light"
                    aria-label="Minimize checklist"
                    onPress={() => setExpanded(false)}
                  >
                    <MinusSignIcon size={16} className="text-zinc-400" />
                  </Button>
                  <Button
                    isIconOnly
                    size="sm"
                    variant="light"
                    aria-label="Dismiss checklist"
                    onPress={dismiss}
                  >
                    <Cancel01Icon size={16} className="text-zinc-400" />
                  </Button>
                </div>
              </div>

              <div className="space-y-2">
                {visibleSteps.map((step) => {
                  const isDone = Boolean(completedAt[step.key]);

                  return (
                    <div
                      key={step.key}
                      className="flex items-center justify-between gap-2 rounded-2xl bg-zinc-900 p-3"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        {isDone ? (
                          <CheckmarkCircle02Icon
                            size={18}
                            className="shrink-0 text-emerald-400"
                          />
                        ) : (
                          <CircleIcon
                            size={18}
                            className="shrink-0 text-zinc-600"
                          />
                        )}
                        <Link
                          as={NextLink}
                          href={step.href}
                          className={`truncate text-sm font-medium ${
                            isDone
                              ? "text-zinc-500 line-through"
                              : "text-zinc-200"
                          }`}
                        >
                          {step.label}
                        </Link>
                      </div>
                      {!isDone && (
                        <Button
                          isIconOnly
                          size="sm"
                          variant="light"
                          aria-label={`Hide ${step.label}`}
                          onPress={() => hideStep(step.key)}
                        >
                          <Cancel01Icon size={14} className="text-zinc-500" />
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
            </m.div>
          )}
        </AnimatePresence>
      </m.div>
    </div>
  );
}
