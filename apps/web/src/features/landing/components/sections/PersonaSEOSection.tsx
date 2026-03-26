"use client";

import type { FAQPage, WithContext } from "schema-dts";
import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";

interface Feature {
  title: string;
  description: string;
}

interface Stat {
  value: string;
  label: string;
}

interface RelatedRole {
  href: string;
  label: string;
  description: string;
}

interface FAQ {
  question: string;
  answer: string;
}

interface PersonaSEOSectionProps {
  persona: string;
  painPoints: string[];
  features: Feature[];
  stats: Stat[];
  faqs: FAQ[];
  relatedRoles: RelatedRole[];
}

export default function PersonaSEOSection({
  persona,
  painPoints,
  features,
  stats,
  faqs,
  relatedRoles,
}: PersonaSEOSectionProps) {
  return (
    <div className="mx-auto max-w-4xl px-6 pb-24 pt-4">
      {/* Stats */}
      <section className="mb-16 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {stats.map((stat) => (
          <div
            key={stat.label}
            className="rounded-2xl bg-zinc-800/60 p-5 text-center"
          >
            <p className="mb-1 text-2xl font-semibold text-primary">
              {stat.value}
            </p>
            <p className="text-sm text-zinc-400">{stat.label}</p>
          </div>
        ))}
      </section>

      {/* Pain Points */}
      <section className="mb-16">
        <h2 className="mb-6 text-3xl font-semibold text-white">
          Challenges {persona} Face Every Day
        </h2>
        <div className="space-y-3">
          {painPoints.map((point) => (
            <div
              key={point}
              className="flex items-start gap-3 rounded-2xl bg-zinc-800/60 p-5"
            >
              <span className="mt-0.5 shrink-0 text-red-400">✕</span>
              <p className="leading-relaxed text-zinc-300">{point}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="mb-16">
        <h2 className="mb-6 text-3xl font-semibold text-white">
          How GAIA Helps {persona}
        </h2>
        <div className="grid gap-6 md:grid-cols-2">
          {features.map((feature) => (
            <div key={feature.title} className="rounded-3xl bg-zinc-800/60 p-6">
              <h3 className="mb-3 text-lg font-medium text-emerald-400">
                {feature.title}
              </h3>
              <p className="leading-relaxed text-zinc-400">
                {feature.description}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* FAQs */}
      {faqs.length > 0 && (
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Frequently Asked Questions
          </h2>
          <FAQAccordion faqs={faqs} />
          <JsonLd
            data={
              {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                mainEntity: faqs.map((faq) => ({
                  "@type": "Question",
                  name: faq.question,
                  acceptedAnswer: {
                    "@type": "Answer",
                    text: faq.answer,
                  },
                })),
              } as WithContext<FAQPage>
            }
          />
        </section>
      )}

      {/* Related Roles */}
      <section>
        <h2 className="mb-6 text-3xl font-semibold text-white">
          GAIA for Other Roles
        </h2>
        <div className="grid gap-4 sm:grid-cols-3">
          {relatedRoles.map((relatedRole) => (
            <a
              key={relatedRole.href}
              href={relatedRole.href}
              className="group rounded-2xl bg-zinc-800/60 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-base font-medium text-white transition-colors group-hover:text-primary">
                {relatedRole.label}
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                {relatedRole.description}
              </p>
            </a>
          ))}
        </div>
      </section>
    </div>
  );
}
