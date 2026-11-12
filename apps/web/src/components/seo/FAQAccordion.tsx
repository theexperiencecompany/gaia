"use client";

import { Accordion } from "@heroui/react";
import { toneVariants } from "@/components/shared/tone";
import {
  ACCORDION_INDICATOR,
  ACCORDION_PANEL,
  ACCORDION_TRIGGER,
} from "@/lib/heroui/accordionParity";

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
              className={`text-lg font-medium ${ACCORDION_TRIGGER}`}
            >
              {faq.question}
              <Accordion.Indicator className={ACCORDION_INDICATOR} />
            </Accordion.Trigger>
          </Accordion.Heading>
          <Accordion.Panel
            className={toneVariants({
              tone: "muted",
              className: `${ACCORDION_PANEL} text-base font-light`,
            })}
          >
            <div className="pb-2">{faq.answer}</div>
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion>
  );
}
