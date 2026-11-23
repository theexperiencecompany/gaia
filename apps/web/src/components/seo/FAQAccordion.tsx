"use client";

import { Accordion } from "@heroui/react";
import { accordionVariants } from "@/components/shared/accordionVariants";
import { toneVariants } from "@/components/shared/tone";

const accordionStyles = accordionVariants();

interface FAQ {
  question: string;
  answer: string;
}

export default function FAQAccordion({ faqs }: { faqs: FAQ[] }) {
  const [firstFaq] = faqs;
  return (
    <Accordion
      variant="default"
      defaultExpandedKeys={firstFaq ? [firstFaq.question] : []}
    >
      {faqs.map((faq) => (
        <Accordion.Item key={faq.question} id={faq.question}>
          <Accordion.Heading>
            <Accordion.Trigger
              className={accordionStyles.trigger({
                className: "text-lg font-medium",
              })}
            >
              {faq.question}
              <Accordion.Indicator className={accordionStyles.indicator()} />
            </Accordion.Trigger>
          </Accordion.Heading>
          <Accordion.Panel>
            <div
              className={toneVariants({
                tone: "muted",
                className: accordionStyles.content({
                  className: "text-base font-light",
                }),
              })}
            >
              <div className="pb-2">{faq.answer}</div>
            </div>
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion>
  );
}
