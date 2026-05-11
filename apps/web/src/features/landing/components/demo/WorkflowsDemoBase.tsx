import { AnimatePresence, useInView } from "motion/react";
import * as m from "motion/react-m";
import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { DemoFinalCard } from "./DemoFinalCards";

const ease = [0.22, 1, 0.36, 1] as const;

export interface WorkflowStep {
  id: string;
  label: string;
  detail: string;
  category: string;
}

interface WorkflowsDemoBaseProps {
  title: string;
  schedule: string;
  steps: WorkflowStep[];
  fallbackIcon?: (isDone: boolean, isRunning: boolean) => ReactNode;
}

function defaultFallbackIcon(isDone: boolean, isRunning: boolean) {
  return (
    <div
      className={`h-2 w-2 rounded-full ${isDone ? "bg-emerald-400" : isRunning ? "animate-pulse bg-primary" : "bg-zinc-600"}`}
    />
  );
}

export function WorkflowsDemoBase({
  title,
  schedule,
  steps,
  fallbackIcon = defaultFallbackIcon,
}: WorkflowsDemoBaseProps) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.3 });
  const [currentStep, setCurrentStep] = useState(1);
  const [done, setDone] = useState(false);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (!inView) return;

    steps.slice(1).forEach((_, i) => {
      timersRef.current.push(
        setTimeout(() => setCurrentStep(i + 2), (i + 1) * 500),
      );
    });
    timersRef.current.push(
      setTimeout(() => setDone(true), steps.length * 500 + 300),
    );

    const captured = timersRef.current;
    return () => {
      for (const t of captured) clearTimeout(t);
    };
  }, [inView, steps]);

  return (
    <div
      ref={ref}
      className="flex flex-col overflow-hidden rounded-3xl bg-zinc-900 p-5 text-left"
      style={{ maxHeight: 420 }}
    >
      <div className="min-h-0 flex-1 overflow-y-auto no-scrollbar">
        <div className="mb-5 rounded-2xl bg-zinc-800 p-4">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-sm font-medium text-zinc-100">{title}</span>
            <AnimatePresence mode="wait">
              {done ? (
                <m.div
                  key="done"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-2.5 py-1"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  <span className="text-[11px] font-medium text-emerald-400">
                    Completed
                  </span>
                </m.div>
              ) : (
                <m.div
                  key="running"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex items-center gap-1.5 rounded-full bg-primary/15 px-2.5 py-1"
                >
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                  <span className="text-[11px] font-medium text-primary">
                    Running
                  </span>
                </m.div>
              )}
            </AnimatePresence>
          </div>
          <span className="text-xs text-zinc-500">{schedule}</span>
        </div>

        <div className="space-y-2">
          {steps.map((step, i) => {
            const isVisible = currentStep > i;
            const isRunning = currentStep === i + 1 && !done;
            const isDone = currentStep > i + 1 || (done && currentStep > i);

            return (
              <AnimatePresence key={step.id}>
                {isVisible && (
                  <m.div
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.3, ease }}
                    className="flex items-center gap-3 rounded-xl bg-zinc-800/60 px-3 py-2.5"
                  >
                    <div className="flex h-5.5 w-5.5 shrink-0 items-center justify-center">
                      {getToolCategoryIcon(step.category, {
                        width: 22,
                        height: 22,
                        showBackground: false,
                      }) ?? fallbackIcon(isDone, isRunning)}
                    </div>
                    <span
                      className={`flex-1 text-sm ${isDone ? "text-zinc-400" : "text-zinc-200"}`}
                    >
                      {step.label}
                    </span>
                    <span className="text-[11px] text-zinc-600">
                      {step.detail}
                    </span>
                    {isDone && (
                      <m.span
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className="text-[11px] font-medium text-emerald-400"
                      >
                        Done
                      </m.span>
                    )}
                    {isRunning && (
                      <span className="animate-pulse text-[11px] font-medium text-primary">
                        Running
                      </span>
                    )}
                  </m.div>
                )}
              </AnimatePresence>
            );
          })}
        </div>

        <AnimatePresence>
          {done && (
            <m.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease, delay: 0.3 }}
              className="mt-4"
            >
              <DemoFinalCard type="briefing" />
            </m.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
