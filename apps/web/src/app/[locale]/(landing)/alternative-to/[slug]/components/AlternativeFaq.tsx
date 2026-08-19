import FAQAccordion from "@/components/seo/FAQAccordion";

interface AlternativeFaqProps {
  readonly t: (key: string) => string;
  readonly faqs: Array<{ question: string; answer: string }>;
}

export function AlternativeFaq({ t, faqs }: AlternativeFaqProps) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        {t("common.faq")}
      </h2>
      <FAQAccordion faqs={faqs} />
    </section>
  );
}
