"use client";

import { Textarea } from "@heroui/input";
import { Tab, Tabs } from "@heroui/tabs";
import { ComputerIcon, SmartPhone01Icon } from "@icons";
import type { PlanDuration } from "@shared/api/generated";
import { useState } from "react";
import type { PaywallConcept } from "./concepts";
import { DeviceFrame, type FrameDevice } from "./DeviceFrame";
import { usePaywallLabFeedback } from "./feedbackStore";
import type { PaywallSubject } from "./labData";

interface ConceptSectionProps {
  index: number;
  concept: PaywallConcept;
  subject: PaywallSubject;
  /** Remounts the concept so its entrance and demo run replay. */
  subjectKey: string;
  onCheckout: (concept: PaywallConcept, period: PlanDuration) => void;
}

const RATIONALE_ROWS = [
  ["The bet", "bet"],
  ["Why it might convert", "whyItConverts"],
  ["The risk", "risk"],
  ["Cost to build for real", "buildCost"],
] as const;

export function ConceptSection({
  index,
  concept,
  subject,
  subjectKey,
  onCheckout,
}: ConceptSectionProps) {
  const [device, setDevice] = useState<FrameDevice>("desktop");
  const note = usePaywallLabFeedback((state) => state.notes[concept.id] ?? "");
  const setNote = usePaywallLabFeedback((state) => state.setNote);
  const { Component } = concept;

  return (
    <section
      id={`concept-${concept.id}`}
      data-concept={concept.id}
      className="grid scroll-mt-6 grid-cols-[minmax(0,1fr)_340px] gap-6 max-[1100px]:grid-cols-1"
    >
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-xl font-semibold text-zinc-100">
            <span className="text-zinc-500 tabular-nums">{index + 1}</span>{" "}
            {concept.name}
          </h2>
          <Tabs
            aria-label={`${concept.name} frame`}
            size="sm"
            radius="full"
            selectedKey={device}
            onSelectionChange={(key) =>
              setDevice(key === "mobile" ? "mobile" : "desktop")
            }
          >
            <Tab
              key="desktop"
              title={
                <span className="flex items-center gap-1.5">
                  <ComputerIcon className="h-4 w-4" /> Desktop
                </span>
              }
            />
            <Tab
              key="mobile"
              title={
                <span className="flex items-center gap-1.5">
                  <SmartPhone01Icon className="h-4 w-4" /> Mobile
                </span>
              }
            />
          </Tabs>
        </div>
        <DeviceFrame device={device}>
          <Component
            key={`${subjectKey}-${device}`}
            subject={subject}
            onCheckout={(period) => onCheckout(concept, period)}
          />
        </DeviceFrame>
      </div>

      <aside className="flex flex-col gap-4 self-start rounded-2xl bg-zinc-900/60 p-5">
        <dl className="space-y-4">
          {RATIONALE_ROWS.map(([label, field]) => (
            <div key={field}>
              <dt className="text-sm font-semibold text-zinc-200">{label}</dt>
              <dd className="mt-1 text-[13px] leading-relaxed text-zinc-400">
                {concept[field]}
              </dd>
            </div>
          ))}
        </dl>
        <Textarea
          label={`Your notes on ${concept.name}`}
          labelPlacement="outside"
          placeholder="What works, what doesn't, what you'd change"
          minRows={4}
          value={note}
          onValueChange={(value) => setNote(concept.id, value)}
        />
      </aside>
    </section>
  );
}
