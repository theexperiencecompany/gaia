"use client";

import { Accordion } from "@heroui/react";

interface FAQ {
  question: string;
  answer: string;
}

export default function FAQAccordion({ faqs }: { faqs: FAQ[] }) {
  const [firstFaq] = faqs;
  return (
    <Accordion
      variant="default"
      className="p-0!"
      defaultExpandedKeys={firstFaq ? [firstFaq.question] : []}
    >
      {faqs.map((faq) => (
        <Accordion.Item key={faq.question} id={faq.question}>
          <Accordion.Heading>
            <Accordion.Trigger className="text-lg font-medium">
              {faq.question}
              <Accordion.Indicator />
            </Accordion.Trigger>
          </Accordion.Heading>
          <Accordion.Panel className="text-base text-zinc-400 font-light pb-4">
            {faq.answer}
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion>
  );
}
