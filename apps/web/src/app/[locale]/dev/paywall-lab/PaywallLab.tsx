"use client";

import { Tab, Tabs } from "@heroui/tabs";
import type { PlanDuration } from "@shared/api/generated";
import { useState } from "react";
import { toast } from "@/lib/toast";
import { ConceptSection } from "./ConceptSection";
import { PAYWALL_CONCEPTS, type PaywallConcept } from "./concepts";
import { LAB_PERSONAS } from "./labData";
import { OverallFeedback } from "./OverallFeedback";

/** Today's paywall, for scale: every concept is a bet against these numbers. */
const FUNNEL_FACTS = [
  "24% of people who see the paywall open checkout",
  "0 of 53 mobile signups paid",
  "0 of 14 yearly checkouts paid",
];

/** The lab never opens Dodo; it says which checkout the real paywall would open. */
function announceCheckout(concept: PaywallConcept, period: PlanDuration) {
  toast.info(`${concept.name}: would open ${period} checkout`);
}

export function PaywallLab() {
  const [personaId, setPersonaId] = useState(LAB_PERSONAS[0].id);
  const persona =
    LAB_PERSONAS.find(({ id }) => id === personaId) ?? LAB_PERSONAS[0];

  return (
    <main className="min-h-screen bg-primary-bg px-8 py-10 text-zinc-100 max-sm:px-4">
      <div className="mx-auto flex max-w-[1320px] flex-col gap-14">
        <header className="flex flex-col gap-5">
          <div>
            <h1 className="text-3xl font-bold text-zinc-100">Paywall lab</h1>
            <p className="mt-2 max-w-[70ch] text-base text-zinc-400">
              Round 2: four ways to show value before the price, each aiming for
              an "it already did something for me" moment. Live parts are mocked
              and labelled. Pick who is signing up, run each one, flip to
              mobile, leave notes, copy them back.
            </p>
            <p className="mt-2 text-[13px] text-zinc-500">
              {FUNNEL_FACTS.join(". ")}.
            </p>
          </div>
          <Tabs
            aria-label="Who is signing up"
            radius="full"
            selectedKey={personaId}
            onSelectionChange={(key) => setPersonaId(String(key))}
          >
            {LAB_PERSONAS.map(({ id, label }) => (
              <Tab key={id} title={label} />
            ))}
          </Tabs>
        </header>

        {PAYWALL_CONCEPTS.map((concept, index) => (
          <ConceptSection
            key={concept.id}
            index={index}
            concept={concept}
            subject={persona.subject}
            mock={persona.mock}
            subjectKey={persona.id}
            onCheckout={announceCheckout}
          />
        ))}

        <OverallFeedback />
      </div>
    </main>
  );
}
