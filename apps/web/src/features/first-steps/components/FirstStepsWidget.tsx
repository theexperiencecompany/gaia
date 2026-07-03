"use client";

import { Button } from "@heroui/button";
import { Link } from "@heroui/link";
import { Progress } from "@heroui/progress";
import {
  ArrowDown01Icon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  CircleIcon,
} from "@icons";
import NextLink from "next/link";
import { useFirstStepsWidget } from "@/features/first-steps/hooks/useFirstStepsWidget";

export function FirstStepsWidget() {
  const {
    shouldRender,
    expanded,
    setExpanded,
    visibleSteps,
    completedAt,
    completedCount,
    totalCount,
    dismissAll,
    hideStep,
  } = useFirstStepsWidget();

  if (!shouldRender) return null;

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className="fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full bg-zinc-800 px-4 py-2 shadow-lg transition hover:bg-zinc-700"
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
      </button>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 z-40 w-80 rounded-2xl bg-zinc-800 p-4 shadow-lg">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-zinc-100">Get started</p>
          <p className="text-xs text-zinc-500">
            {completedCount}/{totalCount} complete
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button
            isIconOnly
            size="sm"
            variant="light"
            aria-label="Collapse"
            onPress={() => setExpanded(false)}
          >
            <ArrowDown01Icon size={16} className="text-zinc-400" />
          </Button>
          <Button
            isIconOnly
            size="sm"
            variant="light"
            aria-label="Dismiss checklist"
            onPress={dismissAll}
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
                  <CircleIcon size={18} className="shrink-0 text-zinc-600" />
                )}
                <Link
                  as={NextLink}
                  href={step.href}
                  className={`truncate text-sm font-medium ${
                    isDone ? "text-zinc-500 line-through" : "text-zinc-200"
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
    </div>
  );
}
