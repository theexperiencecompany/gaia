"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";

import { getAllFAQs } from "@/lib/faq";

export function FAQAccordion() {
  const faqItems = getAllFAQs();

  return (
    <div className="relative flex h-fit w-full items-center justify-center py-20">
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

      <div className="relative z-[1] w-screen max-w-7xl p-8">
        <div className="mb-10 flex w-full flex-col items-start justify-center gap-3">
          <span className="font-serif text-7xl font-medium">
            Frequently asked questions
          </span>
        </div>

        <Accordion
          variant="light"
          className="cursor-pointer p-0!"
          itemClasses={{ titleWrapper: "cursor-pointer" }}
          defaultSelectedKeys={["0"]}
        >
          {faqItems.map((item) => (
            <AccordionItem
              key={item.question}
              aria-label={item.question}
              title={item.question}
              classNames={{
                heading: "font-normal",
                title: "text-2xl",
                content:
                  "text-xl max-w-[60%] text-foreground-500 font-light mb-6",
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
