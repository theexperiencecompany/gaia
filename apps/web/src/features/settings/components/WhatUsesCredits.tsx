"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";

const COSTS: { label: string; credits: string }[] = [
  { label: "Chat message", credits: "7–80" },
  { label: "Web search", credits: "100" },
  { label: "Image generation", credits: "500" },
  { label: "Deep research", credits: "500–1,500" },
];

export function WhatUsesCredits() {
  return (
    <Accordion variant="light" className="px-0">
      <AccordionItem
        key="costs"
        aria-label="What uses credits"
        title={
          <span className="text-sm text-zinc-300">What uses credits?</span>
        }
        classNames={{ content: "pb-3" }}
      >
        <div className="space-y-1.5">
          {COSTS.map((c) => (
            <div
              key={c.label}
              className="flex items-center justify-between text-sm"
            >
              <span className="text-zinc-400">{c.label}</span>
              <span className="text-zinc-500">{c.credits} credits</span>
            </div>
          ))}
          <p className="pt-2 text-xs text-zinc-600">
            A credit is our unit of AI compute. 10,000 credits = $1 of usage.
          </p>
        </div>
      </AccordionItem>
    </Accordion>
  );
}
