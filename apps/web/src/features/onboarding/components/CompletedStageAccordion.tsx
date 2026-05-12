/**
 * Generic post-ack stage row used by every completed onboarding stage. Mirrors
 * the `CollapsedWritingStyle` look so the timeline reads as one consistent
 * visual language: a left-indented pill with a green checkmark + title that
 * expands into the stage's full payload. The width grows when expanded so
 * embedded cards (workflow grid, run-now transcript, etc.) get room to breathe.
 */

"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { CheckmarkCircle02Icon } from "@icons";
import * as m from "motion/react-m";
import { type ReactNode, useState } from "react";
import { EASE_OUT_QUART } from "../constants/motion";

interface CompletedStageAccordionProps {
  /** Stable key for the AccordionItem — must be unique within the timeline. */
  itemKey: string;
  /** ARIA label / collapsed title text. */
  title: string;
  /** Expandable contents — rendered inside `px-3 pt-2 pb-3`. */
  children: ReactNode;
  /** Optional motion delay so stacked accordions cascade in. */
  delay?: number;
}

export function CompletedStageAccordion({
  itemKey,
  title,
  children,
  delay = 0,
}: CompletedStageAccordionProps) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <m.div
      className={`ml-10.75 rounded-2xl bg-zinc-800/40 p-1 backdrop-blur-xl transition-[width,max-width] duration-300 ${
        isOpen ? "w-full" : "w-96"
      }`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: EASE_OUT_QUART, delay }}
    >
      <Accordion
        variant="light"
        className="px-0"
        onSelectionChange={(keys) => {
          const set = keys as Set<string | number>;
          setIsOpen(set.size > 0);
        }}
        itemClasses={{
          base: "px-0",
          trigger: "px-3 py-2 rounded-2xl data-[hover=true]:bg-zinc-700/40",
          titleWrapper: "py-0",
          content: "px-3 pt-2 pb-3",
        }}
      >
        <AccordionItem
          key={itemKey}
          aria-label={title}
          title={
            <div className="flex items-center gap-2">
              <CheckmarkCircle02Icon className="size-4 text-emerald-500" />
              <span className="text-sm font-medium text-zinc-200">{title}</span>
            </div>
          }
        >
          {children}
        </AccordionItem>
      </Accordion>
    </m.div>
  );
}
