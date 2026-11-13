"use client";

import { Accordion } from "@heroui/react";
import Link from "next/link";

import { type FAQItem, getAllFAQs } from "@/lib/faq";
import {
  ACCORDION_INDICATOR,
  ACCORDION_PANEL,
  ACCORDION_TRIGGER,
} from "@/lib/heroui/accordionParity";

export function FAQAccordion({ faqs }: { faqs?: FAQItem[] }) {
  const faqItems = faqs ?? getAllFAQs();

  return (
    <div className="relative flex h-fit w-full items-center justify-center px-2 py-8 sm:px-4">
      {/* <div
        className="pointer-events-none absolute top-0 right-0 z-0 h-screen w-screen"
        style={{
          backgroundImage: `
              radial-gradient(
                circle at top right,
                #00bbff40,
                transparent 70%
              )
            `,
          filter: "blur(100px)",
          backgroundRepeat: "no-repeat",
        }}
      /> */}

      <div className="relative z-1 w-full max-w-7xl px-0 py-4 sm:p-8">
        <div className="mb-10 flex w-full flex-col items-start justify-center gap-3">
          <span className="font-serif text-4xl sm:text-5xl lg:text-7xl font-medium">
            FAQ
          </span>
          <Link
            href="/faq"
            className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
          >
            See every question about GAIA
          </Link>
        </div>

        <Accordion
          variant="default"
          className="cursor-pointer p-0!"
          defaultExpandedKeys={faqItems[0] ? [faqItems[0].question] : []}
        >
          {faqItems.map((item) => (
            <Accordion.Item key={item.question} id={item.question}>
              <Accordion.Heading className="font-normal">
                <Accordion.Trigger
                  className={`cursor-pointer text-lg sm:text-2xl ${ACCORDION_TRIGGER}`}
                >
                  {item.question}
                  <Accordion.Indicator className={ACCORDION_INDICATOR} />
                </Accordion.Trigger>
              </Accordion.Heading>
              <Accordion.Panel
                className={`${ACCORDION_PANEL} mb-6 max-w-full text-base font-light text-foreground-500 sm:max-w-[60%] sm:text-xl`}
              >
                <span className="select-text">{item.answer}</span>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      </div>
    </div>
  );
}
