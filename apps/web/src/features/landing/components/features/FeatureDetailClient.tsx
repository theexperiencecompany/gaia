"use client";

import { ArrowDown01Icon } from "@icons";
import { m } from "motion/react";
import Link from "next/link";
import { useState } from "react";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import {
  type FeatureData,
  getFeatureBySlug,
} from "@/features/landing/data/featuresData";
import { FeatureDemoWrapper } from "./FeatureDemoWrapper";
import { FeatureIcon } from "./FeatureIcon";

interface Props {
  feature: FeatureData;
}

const ease = [0.22, 1, 0.36, 1] as const;

export function FeatureDetailClient({ feature }: Props) {
  const [openFaq, setOpenFaq] = useState<number | null>(null);

  return (
    <div className="w-full bg-[#111111] min-h-screen">
      {/* Back link */}
      <div className="pt-6 px-6">
        <Link
          href="/features"
          className="text-xs text-zinc-500 hover:text-zinc-300 flex items-center gap-1 transition-colors"
        >
          ← All features
        </Link>
      </div>

      {/* Hero */}
      <section className="pt-16 pb-12 max-w-3xl mx-auto px-6 text-center">
        <m.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
          className="text-xs uppercase tracking-widest text-[#00bbff] mb-4"
        >
          {feature.category}
        </m.div>
        <m.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.1 }}
          className="font-serif text-4xl md:text-5xl lg:text-6xl font-normal text-zinc-50 mb-6 leading-[1.1]"
        >
          {feature.headline}
        </m.h1>
        <m.p
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.2 }}
          className="text-base md:text-lg font-light text-zinc-400 max-w-2xl mx-auto mb-8"
        >
          {feature.subheadline}
        </m.p>
        <m.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.3 }}
        >
          <GetStartedButton />
        </m.div>
      </section>

      {/* Demo section */}
      <m.div
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        viewport={{ once: true }}
        className="max-w-4xl mx-auto px-6 py-8"
      >
        <div className="rounded-2xl bg-zinc-800 p-4">
          <div className="rounded-2xl bg-zinc-900 p-4 md:p-6">
            <FeatureDemoWrapper demoComponent={feature.demoComponent} />
          </div>
        </div>
      </m.div>

      {/* Benefits */}
      <m.section
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        viewport={{ once: true }}
        className="max-w-6xl mx-auto px-6 py-16"
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {feature.benefits.map((benefit) => (
            <div key={benefit.title} className="rounded-2xl bg-zinc-800 p-6">
              <div className="bg-[#00bbff]/10 rounded-xl p-2 w-9 h-9 mb-4 flex items-center justify-center">
                <FeatureIcon name={benefit.icon} />
              </div>
              <h3 className="text-sm font-medium text-zinc-100 mb-2">
                {benefit.title}
              </h3>
              <p className="text-sm font-light text-zinc-400 leading-relaxed">
                {benefit.description}
              </p>
            </div>
          ))}
        </div>
      </m.section>

      {/* Use Cases */}
      {feature.useCases && (
        <m.section
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          viewport={{ once: true }}
          className="max-w-6xl mx-auto px-6 py-12"
        >
          <h2 className="text-2xl font-serif font-normal text-zinc-50 text-center mb-10">
            How teams use this
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {feature.useCases.map((uc) => (
              <div key={uc.title} className="rounded-2xl bg-zinc-800 p-6">
                <h3 className="text-sm font-medium text-zinc-100 mb-2">
                  {uc.title}
                </h3>
                <p className="text-sm font-light text-zinc-400 leading-relaxed">
                  {uc.description}
                </p>
              </div>
            ))}
          </div>
        </m.section>
      )}

      {/* How it works */}
      {feature.howItWorks && (
        <m.section
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          viewport={{ once: true }}
          className="max-w-4xl mx-auto px-6 py-12"
        >
          <h2 className="text-2xl font-serif font-normal text-zinc-50 text-center mb-10">
            How it works
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {feature.howItWorks.map((step) => (
              <div key={step.number} className="flex flex-col gap-2">
                <span className="text-4xl font-mono text-zinc-700">
                  {step.number}
                </span>
                <h3 className="text-sm font-medium text-zinc-100">
                  {step.title}
                </h3>
                <p className="text-sm font-light text-zinc-400">
                  {step.description}
                </p>
              </div>
            ))}
          </div>
        </m.section>
      )}

      {/* FAQ */}
      {feature.faqs && (
        <m.section
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          viewport={{ once: true }}
          className="max-w-3xl mx-auto px-6 py-12"
        >
          <h2 className="text-2xl font-serif font-normal text-zinc-50 text-center mb-10">
            Frequently asked questions
          </h2>
          <div className="flex flex-col gap-2">
            {feature.faqs.map((faq, i) => (
              <div
                key={faq.question}
                className="rounded-2xl bg-zinc-800 overflow-hidden"
              >
                <button
                  type="button"
                  onClick={() => setOpenFaq(openFaq === i ? null : i)}
                  className="w-full flex items-center justify-between px-6 py-4 text-left"
                >
                  <span className="text-sm font-medium text-zinc-100">
                    {faq.question}
                  </span>
                  <span
                    className={`text-zinc-400 transition-transform duration-200 ${openFaq === i ? "rotate-180" : ""}`}
                  >
                    <ArrowDown01Icon size={16} />
                  </span>
                </button>
                {openFaq === i && (
                  <div className="px-6 pb-5">
                    <p className="text-sm font-light text-zinc-400 leading-relaxed">
                      {faq.answer}
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </m.section>
      )}

      {/* Related Features */}
      {feature.relatedSlugs && (
        <m.section
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          viewport={{ once: true }}
          className="max-w-6xl mx-auto px-6 py-12"
        >
          <h2 className="text-2xl font-serif font-normal text-zinc-50 text-center mb-10">
            Related features
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {feature.relatedSlugs.map((slug) => {
              const related = getFeatureBySlug(slug);
              if (!related) return null;
              return (
                <Link
                  key={slug}
                  href={`/features/${slug}`}
                  className="rounded-2xl bg-zinc-800 p-6 hover:bg-zinc-700 transition-colors"
                >
                  <div className="bg-[#00bbff]/10 rounded-xl p-2 w-9 h-9 mb-4 flex items-center justify-center">
                    <FeatureIcon name={related.icon} />
                  </div>
                  <h3 className="text-sm font-medium text-zinc-100 mb-1">
                    {related.title}
                  </h3>
                  <p className="text-xs font-light text-zinc-500 leading-relaxed">
                    {related.tagline}
                  </p>
                </Link>
              );
            })}
          </div>
        </m.section>
      )}

      <FinalSection />
    </div>
  );
}
