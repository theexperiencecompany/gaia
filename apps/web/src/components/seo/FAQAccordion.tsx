"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";

interface FAQ {
  question: string;
  answer: string;
}

export default function FAQAccordion({ faqs }: { faqs: FAQ[] }) {
  const [firstFaq] = faqs;
  return (
    <Accordion
      variant="light"
      className="p-0!"
      defaultSelectedKeys={firstFaq ? [firstFaq.question] : []}
    >
      {faqs.map((faq) => (
        <AccordionItem
          key={faq.question}
          aria-label={faq.question}
          title={faq.question}
          classNames={{
            title: "text-lg font-medium",
            content: "text-base text-zinc-400 font-light pb-4",
          }}
        >
          {faq.answer}
        </AccordionItem>
      ))}
    </Accordion>
  );
}
