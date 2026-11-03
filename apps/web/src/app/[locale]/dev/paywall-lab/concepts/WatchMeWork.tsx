"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { CheckmarkCircle02Icon, Refresh01Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useMemo } from "react";
import { OnboardingBotBubble } from "@/features/onboarding/components/OnboardingBotBubble";
import { MOTION_FADE_UP } from "@/features/onboarding/constants/motion";
import { formatWholeOrCents } from "@/features/pricing/utils/money";
import {
  MONTHLY_PRICE_MINOR,
  type PaywallConceptProps,
  PRICE_CURRENCY,
  YEARLY_PRICE_MINOR,
} from "../labData";
import { CheckoutDock } from "./CheckoutDock";
import { demoScriptFor } from "./demoScript";
import { useDemoRun } from "./useDemoRun";

/** Concept 1: GAIA does one job in front of them, then names the price. */
export function WatchMeWork({ subject, onCheckout }: PaywallConceptProps) {
  const script = useMemo(() => demoScriptFor(subject), [subject]);
  const { doneCount, isDone, elapsedSeconds, replay } = useDemoRun(
    script.steps.length,
  );
  const opener = subject.firstName
    ? `Before we talk money, ${subject.firstName}, let me just do something.`
    : "Before we talk money, let me just do something.";

  return (
    <div className="flex flex-1 flex-col gap-5">
      <OnboardingBotBubble text={opener} />

      <div className="rounded-2xl bg-zinc-800 p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-base font-semibold text-zinc-100">
            {script.title}
          </p>
          <span className="text-[13px] text-zinc-500 tabular-nums">
            0:{String(elapsedSeconds).padStart(2, "0")}
          </span>
        </div>
        <ol className="space-y-2 rounded-xl bg-zinc-900 p-3">
          {script.steps.map((step, index) => (
            <li key={step.label} className="flex items-start gap-3">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
                {index < doneCount ? (
                  <CheckmarkCircle02Icon className="h-5 w-5 text-primary" />
                ) : index === doneCount ? (
                  <Spinner size="sm" color="default" />
                ) : (
                  <span className="h-1.5 w-1.5 rounded-full bg-zinc-700" />
                )}
              </span>
              <div
                className={index <= doneCount ? "opacity-100" : "opacity-40"}
              >
                <p className="text-sm text-zinc-200">{step.label}</p>
                {step.detail && (
                  <p className="text-[13px] text-zinc-500">{step.detail}</p>
                )}
              </div>
            </li>
          ))}
        </ol>
        <AnimatePresence>
          {isDone && (
            <m.div
              className="mt-3 rounded-xl bg-zinc-900 p-3"
              {...MOTION_FADE_UP}
            >
              <p className="text-[13px] text-zinc-500">
                {script.artifactLabel}
              </p>
              <p className="mt-1 text-sm leading-relaxed text-zinc-200">
                {script.artifact}
              </p>
            </m.div>
          )}
        </AnimatePresence>
      </div>

      <AnimatePresence>
        {isDone && (
          <m.div className="flex flex-1 flex-col gap-5" {...MOTION_FADE_UP}>
            <div className="flex items-start justify-between gap-3">
              <p className="text-base leading-relaxed text-zinc-200">
                That took me {elapsedSeconds} seconds. {script.closer}
              </p>
              <Button
                isIconOnly
                size="sm"
                variant="light"
                aria-label="Replay the demo"
                onPress={replay}
              >
                <Refresh01Icon className="h-4 w-4 text-zinc-500" />
              </Button>
            </div>
            <CheckoutDock
              label={`Put me to work, ${formatWholeOrCents(MONTHLY_PRICE_MINOR, PRICE_CURRENCY)}/month`}
              onPress={() => onCheckout("monthly")}
            >
              <Button
                size="sm"
                variant="light"
                className="text-zinc-500"
                onPress={() => onCheckout("yearly")}
              >
                or {formatWholeOrCents(YEARLY_PRICE_MINOR, PRICE_CURRENCY)} for
                the year
              </Button>
            </CheckoutDock>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}
