/** Every FAQ answer is in the server HTML, collapsed or not, so the page shows crawlers what its FAQPage schema claims. */
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";

import FAQAccordion from "@/components/seo/FAQAccordion";
import FAQPageClient from "@/features/faq/components/FAQPageClient";
import { FAQAccordion as HomepageFAQAccordion } from "@/features/pricing/components/FAQAccordion";

const FAQS = [
  { question: "First question?", answer: "The first answer is open." },
  { question: "Second question?", answer: "The second answer starts closed." },
  { question: "Third question?", answer: "The third answer starts closed." },
];

describe("FAQ answers in server HTML", () => {
  it.each([
    ["FAQAccordion", () => renderToString(<FAQAccordion faqs={FAQS} />)],
    ["FAQPageClient", () => renderToString(<FAQPageClient faqs={FAQS} />)],
    [
      "HomepageFAQAccordion",
      () => renderToString(<HomepageFAQAccordion faqs={FAQS} />),
    ],
  ])("%s renders every answer", (_name, render) => {
    const html = render();
    for (const { answer } of FAQS) expect(html).toContain(answer);
  });
});
