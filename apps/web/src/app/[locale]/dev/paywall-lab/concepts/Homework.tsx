"use client";

import { Chip } from "@heroui/chip";
import { ArrowRight01Icon } from "@icons";
import * as m from "motion/react-m";
import { useEffect } from "react";
import { MOTION_FADE_UP } from "@/features/onboarding/constants/motion";
import type { PaywallConceptProps } from "../labData";
import { PriceDock } from "./PriceDock";
import { RunProgress } from "./RunProgress";
import { useStagedRun } from "./useStagedRun";
import { ValueHeadline } from "./ValueHeadline";

const RUN_MS = 3500;

/** Concept 4: no connect. GAIA researches them from public sources while they answer, and opens with what it found. */
export function Homework({ subject, mock, onCheckout }: PaywallConceptProps) {
  const { homework } = mock;
  const { stage, progress, start } = useStagedRun(RUN_MS);

  useEffect(() => {
    start();
  }, [start]);

  if (stage !== "done")
    return (
      <RunProgress
        label="Looking you up"
        items={homework.findings.map((finding) => finding.source)}
        total={homework.findings.length}
        unit="sources"
        progress={progress}
      />
    );

  return (
    <m.div className="flex flex-1 flex-col gap-6" {...MOTION_FADE_UP}>
      <ValueHeadline
        headline={
          subject.firstName
            ? `I did some homework on you, ${subject.firstName}.`
            : "I did some homework on you."
        }
        line="Public sources only, nothing you connected. Here's where I'd start on Monday."
      />

      <div className="rounded-2xl bg-zinc-800 p-4">
        <p className="text-base font-medium text-zinc-100">
          {homework.whoTheyAre}
        </p>
        <ol className="mt-3 flex flex-col gap-2">
          {homework.findings.map((finding) => (
            <li key={finding.fact} className="rounded-xl bg-zinc-900 p-3">
              <Chip size="sm" variant="flat" className="mb-2">
                {finding.source}
              </Chip>
              <p className="text-sm leading-relaxed text-zinc-200">
                {finding.fact}
              </p>
              <p className="mt-1.5 flex items-start gap-1.5 text-sm text-zinc-400">
                <ArrowRight01Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                {finding.action}
              </p>
            </li>
          ))}
        </ol>
      </div>

      <p className="text-[13px] text-zinc-500">
        Not you, or too much? Say so and I'll forget all of it.
      </p>
      <PriceDock keepLabel="Start on these" onCheckout={onCheckout} />
    </m.div>
  );
}
