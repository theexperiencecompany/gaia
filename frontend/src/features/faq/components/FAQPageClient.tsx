"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
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
          variant="light"
          className="cursor-pointer p-0!"
          itemClasses={{ titleWrapper: "cursor-pointer" }}
          defaultSelectedKeys={["0"]}
        >
          {faqs.map((item) => (
            <AccordionItem
              key={item.question}
              aria-label={item.question}
              title={item.question}
              classNames={{
                heading: "font-normal",
                title: "text-2xl",
                content:
                  "text-xl max-w-[90%] text-foreground-500 font-light mb-6",
              }}
            >
              <span className="select-text">{item.answer}</span>
            </AccordionItem>
          ))}
        </Accordion>
      </div>
    </div>
  );
}
