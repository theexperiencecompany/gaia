"use client";

import { Accordion } from "@heroui/react";
import type { FAQItem } from "@/lib/faq";

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

        <Accordion
          variant="default"
          className="cursor-pointer p-0!"
          defaultExpandedKeys={faqs[0] ? [faqs[0].question] : []}
        >
          {faqs.map((item) => (
            <Accordion.Item key={item.question} id={item.question}>
              <Accordion.Heading className="font-normal">
                <Accordion.Trigger className="cursor-pointer text-2xl">
                  {item.question}
                  <Accordion.Indicator />
                </Accordion.Trigger>
              </Accordion.Heading>
              <Accordion.Panel className="text-xl max-w-[90%] text-foreground-500 font-light mb-6">
                <span className="select-text">{item.answer}</span>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      </div>
    </div>
  );
}
