"use client";

import { Accordion } from "@heroui/react";
import { accordionVariants } from "@/components/shared/accordionVariants";
import { toneVariants } from "@/components/shared/tone";
import type { FAQItem } from "@/lib/faq";

const accordionStyles = accordionVariants();

interface FAQPageClientProps {
  faqs: FAQItem[];
}

export default function FAQPageClient({ faqs }: FAQPageClientProps) {
  return (
    <div className="flex min-h-screen w-screen justify-center py-28 pt-40">
      <div className="w-full max-w-5xl">
        <div className="mb-16 flex flex-col items-start justify-center gap-4">
          <h1 className="font-serif text-7xl font-medium tracking-tight">
            Frequently Asked Questions
          </h1>
          <p className="text-xl text-foreground-500">
            Everything you need to know about GAIA and how it works.
          </p>
        </div>

        <h2 className="sr-only">Frequently asked questions</h2>
        <Accordion
          variant="default"
          className="cursor-pointer"
          defaultExpandedKeys={faqs[0] ? [faqs[0].question] : []}
        >
          {faqs.map((item) => (
            <Accordion.Item key={item.question} id={item.question}>
              <Accordion.Heading className="font-normal">
                <Accordion.Trigger
                  className={accordionStyles.trigger({
                    className: "cursor-pointer text-2xl",
                  })}
                >
                  {item.question}
                  <Accordion.Indicator
                    className={accordionStyles.indicator()}
                  />
                </Accordion.Trigger>
              </Accordion.Heading>
              <Accordion.Panel
                className={toneVariants({
                  tone: "muted",
                  className: accordionStyles.panel({
                    className: "mb-6 max-w-[90%] text-xl font-light",
                  }),
                })}
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
