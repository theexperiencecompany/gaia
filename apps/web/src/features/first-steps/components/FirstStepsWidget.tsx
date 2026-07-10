"use client";

import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import { Progress } from "@heroui/progress";
import { Cancel01Icon, CheckmarkCircle02Icon, CircleIcon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import NextLink from "next/link";
import { useFirstStepsWidget } from "@/features/first-steps/hooks/useFirstStepsWidget";

// Elastic: enough overshoot that the shell visibly stretches into place.
const elasticSpring = {
  type: "spring",
  stiffness: 350,
  damping: 22,
  mass: 0.8,
} as const;

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
  } = useFirstStepsWidget();

  if (!shouldRender) return null;

  return (
    <div className="fixed right-4 bottom-4 z-40">
      {/* One shared shell (layoutId) morphs between pill and panel — a
          stretch, not a fade. */}
      <AnimatePresence initial={false} mode="popLayout">
        {!expanded ? (
          <m.button
            key="pill"
            layoutId="first-steps-shell"
            type="button"
            transition={elasticSpring}
            style={{ borderRadius: 9999 }}
            onClick={() => setExpanded(true)}
            className="flex items-center gap-2 bg-zinc-800 px-4 py-2 shadow-lg transition-colors hover:bg-zinc-700"
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
          <m.div
            key="panel"
            layoutId="first-steps-shell"
            transition={elasticSpring}
            style={{ borderRadius: 16 }}
            className="w-80 bg-zinc-800 p-4 shadow-lg"
          >
            <div className="mb-3 flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-zinc-100">
                  Get started
                </p>
                <p className="text-xs text-zinc-500">
                  {completedCount}/{totalCount} complete
                </p>
              </div>
              <Button
                isIconOnly
                size="sm"
                variant="light"
                aria-label="Minimize checklist"
                onPress={() => setExpanded(false)}
              >
                <Cancel01Icon size={16} className="text-zinc-400" />
              </Button>
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
    </div>
  );
}
